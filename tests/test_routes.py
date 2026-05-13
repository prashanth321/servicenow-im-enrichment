"""Integration tests for the auth API routes using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def _get_token(client) -> str:
    """Helper: login and return a valid Bearer token from the httpOnly cookie."""
    resp = client.post("/api/login", json={
        "email": "admin@servicenow.com",
        "password": "admin123",
    })
    return resp.cookies.get("im_auth_token")


def _auth(token: str) -> dict:
    """Helper: return Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/login ───────────────────────────────────────────────────

class TestLoginEndpoint:
    def test_login_success(self, client):
        resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "admin@servicenow.com"
        assert data["role"] == "admin"
        # Token is in httpOnly cookie, NOT in response body
        assert "token" not in data
        assert "im_auth_token" in resp.cookies

    def test_login_wrong_password(self, client):
        resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        resp = client.post("/api/login", json={
            "email": "nobody@example.com",
            "password": "password",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        resp = client.post("/api/login", json={
            "email": "",
            "password": "",
        })
        assert resp.status_code == 400


# ── GET /api/verify (Bearer token) ────────────────────────────────────

class TestVerifyEndpoint:
    def test_verify_valid_bearer_token(self, client):
        token = _get_token(client)
        resp = client.get("/api/verify", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["valid"] is True
        assert resp.json()["email"] == "admin@servicenow.com"

    def test_verify_missing_token(self, client):
        resp = client.get("/api/verify")
        assert resp.status_code in (401, 403)

    def test_verify_invalid_token(self, client):
        resp = client.get("/api/verify", headers=_auth("garbage"))
        assert resp.status_code == 401


# ── POST /api/logout ─────────────────────────────────────────────────

class TestLogoutEndpoint:
    def test_logout(self, client):
        resp = client.post("/api/logout")
        assert resp.status_code == 200
        assert "message" in resp.json()


# ── CORS headers ──────────────────────────────────────────────────────

class TestCORS:
    def test_cors_allows_configured_origin(self, client):
        resp = client.options(
            "/api/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejects_unknown_origin(self, client):
        resp = client.options(
            "/api/login",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Should NOT include the evil origin
        allow = resp.headers.get("access-control-allow-origin", "")
        assert "evil.com" not in allow


# ── Auth enforcement on protected routes ──────────────────────────────

class TestAuthEnforcement:
    def test_contacts_requires_auth(self, client):
        resp = client.get("/contacts")
        assert resp.status_code in (401, 403)

    def test_contacts_with_auth(self, client):
        token = _get_token(client)
        resp = client.get("/contacts", headers=_auth(token))
        assert resp.status_code == 200

    def test_users_search_requires_auth(self, client):
        resp = client.get("/users/search?q=test")
        assert resp.status_code in (401, 403)

    def test_active_p2_requires_auth(self, client):
        resp = client.get("/incidents/list/active-p2")
        assert resp.status_code in (401, 403)


# ── Webhook secret ────────────────────────────────────────────────────

class TestWebhookSecret:
    def test_webhook_rejects_no_secret(self, client):
        resp = client.post("/webhook", json={
            "sys_id": "abc", "number": "INC001", "priority": "2",
            "short_description": "test",
        })
        assert resp.status_code == 403

    def test_webhook_rejects_wrong_secret(self, client):
        resp = client.post("/webhook", json={
            "sys_id": "abc", "number": "INC001", "priority": "2",
            "short_description": "test",
        }, headers={"X-Webhook-Secret": "wrong"})
        assert resp.status_code == 403


# ── SYSPARM sanitization ─────────────────────────────────────────────

class TestSysparmSanitization:
    def test_sanitize_strips_caret(self):
        from utils.api_client import sanitize_sysparm
        assert sanitize_sysparm("test^active=false") == "testactive=false"

    def test_sanitize_strips_newlines(self):
        from utils.api_client import sanitize_sysparm
        assert sanitize_sysparm("test\ninjection\r") == "testinjection"

    def test_sanitize_clean_input_unchanged(self):
        from utils.api_client import sanitize_sysparm
        assert sanitize_sysparm("INC0012345") == "INC0012345"


# ── SN field extraction helpers ───────────────────────────────────────

class TestSnFieldHelpers:
    def test_extract_value_from_dict(self):
        from utils.sn_fields import extract_value
        assert extract_value({"value": "abc", "display_value": "ABC"}) == "abc"

    def test_extract_value_from_string(self):
        from utils.sn_fields import extract_value
        assert extract_value("abc") == "abc"

    def test_extract_value_none(self):
        from utils.sn_fields import extract_value
        assert extract_value(None) is None

    def test_extract_display_from_dict(self):
        from utils.sn_fields import extract_display
        assert extract_display({"value": "abc", "display_value": "ABC"}) == "ABC"

    def test_extract_display_prefers_display_value(self):
        from utils.sn_fields import extract_display
        assert extract_display({"display_value": "Nice", "value": "raw"}) == "Nice"

    def test_extract_display_str_never_none(self):
        from utils.sn_fields import extract_display_str
        assert extract_display_str(None) == ""


# ── Store eviction ────────────────────────────────────────────────────

class TestStoreEviction:
    def test_evict_oldest_caps_size(self):
        from utils.persistence import evict_oldest
        store = {f"INC{i:04d}": [f"data_{i}"] for i in range(10)}
        evict_oldest(store, max_keys=5)
        assert len(store) == 5
        assert "INC0000" not in store
        assert "INC0009" in store

    def test_evict_oldest_noop_under_limit(self):
        from utils.persistence import evict_oldest
        store = {"a": 1, "b": 2}
        evict_oldest(store, max_keys=5)
        assert len(store) == 2


# ── Correlation ID middleware ─────────────────────────────────────────

class TestCorrelationID:
    def test_response_has_request_id_header(self, client):
        resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        assert "x-request-id" in resp.headers

    def test_custom_request_id_echoed(self, client):
        custom_id = "test-correlation-123"
        resp = client.post("/api/logout", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("x-request-id") == custom_id


# ── Content Security Policy ──────────────────────────────────────────

class TestCSPHeaders:
    def test_csp_header_present(self, client):
        resp = client.get("/login")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_x_frame_options_deny(self, client):
        resp = client.get("/login")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options(self, client):
        resp = client.get("/login")
        assert resp.headers.get("x-content-type-options") == "nosniff"


# ── Cookie-based auth ────────────────────────────────────────────────

class TestCookieAuth:
    def test_login_sets_httponly_cookie(self, client):
        resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        assert "im_auth_token" in resp.cookies
        # Verify httponly flag in Set-Cookie header
        set_cookie = resp.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()

    def test_verify_works_with_cookie(self, client):
        # Login to get the cookie
        login_resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        # TestClient automatically sends cookies on subsequent requests
        resp = client.get("/api/verify")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_logout_clears_cookie(self, client):
        # Login first
        client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        resp = client.post("/api/logout")
        assert resp.status_code == 200
        # Cookie should be cleared (max-age=0 or expired)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "im_auth_token" in set_cookie


# ── Role-based access control ─────────────────────────────────────────

class TestRoleBasedAccess:
    def _get_readonly_token(self):
        """Generate a valid token for a readonly user (bypasses rate limiter)."""
        from services.auth_service import generate_token
        # Temporarily ensure the user exists by using the token generator directly
        import json, hashlib, hmac, base64, time
        from services.auth_service import _SECRET, _TOKEN_EXPIRY_SECONDS
        payload = json.dumps({
            "email": "readonly@servicenow.com",
            "role": "readonly",
            "exp": int(time.time()) + _TOKEN_EXPIRY_SECONDS,
        })
        signature = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        return f"{encoded}.{signature}"

    def _get_admin_token(self):
        """Generate a valid token for an admin user (bypasses rate limiter)."""
        import json, hashlib, hmac, base64, time
        from services.auth_service import _SECRET, _TOKEN_EXPIRY_SECONDS
        payload = json.dumps({
            "email": "admin@servicenow.com",
            "role": "admin",
            "exp": int(time.time()) + _TOKEN_EXPIRY_SECONDS,
        })
        signature = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        return f"{encoded}.{signature}"

    def test_readonly_cannot_create_sla_clock(self, client):
        token = self._get_readonly_token()
        resp = client.post(
            "/incidents/INC0010001/sla",
            json={"label": "Test SLA", "target_minutes": 30},
            headers=_auth(token),
        )
        assert resp.status_code == 403

    def test_admin_can_create_sla_clock(self, client):
        token = self._get_admin_token()
        resp = client.post(
            "/incidents/INC0010001/sla",
            json={"label": "Test SLA", "target_minutes": 30},
            headers=_auth(token),
        )
        assert resp.status_code == 201

    def test_readonly_cannot_add_stakeholder(self, client):
        token = self._get_readonly_token()
        resp = client.post(
            "/incidents/INC0010001/stakeholders",
            json={"name": "Test User", "role": "observer"},
            headers=_auth(token),
        )
        assert resp.status_code == 403

    def test_readonly_can_read_sla(self, client):
        token = self._get_readonly_token()
        resp = client.get(
            "/incidents/INC0010001/sla",
            headers=_auth(token),
        )
        assert resp.status_code == 200


# ── Enrichment tracker ────────────────────────────────────────────────

class TestEnrichmentTracker:
    def test_is_recently_enriched_false_when_empty(self):
        from utils.enrichment_tracker import is_recently_enriched
        assert is_recently_enriched("INC_NONEXISTENT_999") is False

    def test_full_audit_lifecycle(self):
        from utils.enrichment_tracker import (
            EnrichmentStep,
            complete_enrichment,
            get_audit_trail,
            record_step,
            start_enrichment,
        )
        audit = start_enrichment("INC_TEST_AUDIT", "sys123", "poll")
        record_step(audit, EnrichmentStep.CI_LOOKUP, "success", "CI found")
        record_step(audit, EnrichmentStep.ONCALL_LOOKUP, "skipped", "No group")
        complete_enrichment(audit, "partial")

        trail = get_audit_trail("INC_TEST_AUDIT")
        assert len(trail) >= 1
        latest = trail[-1]
        assert latest["overall_status"] == "partial"
        assert latest["triggered_by"] == "poll"
        assert len(latest["steps"]) == 2

    def test_enrichment_audit_endpoint(self, client):
        import json, hashlib, hmac, base64, time
        from services.auth_service import _SECRET, _TOKEN_EXPIRY_SECONDS
        payload = json.dumps({
            "email": "admin@servicenow.com",
            "role": "admin",
            "exp": int(time.time()) + _TOKEN_EXPIRY_SECONDS,
        })
        signature = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        token = f"{encoded}.{signature}"
        resp = client.get(
            "/enrichment/audit/INC0010001",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
