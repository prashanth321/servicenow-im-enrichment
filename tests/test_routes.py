"""Integration tests for the auth API routes using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def _get_token(client) -> str:
    """Helper: login and return a valid Bearer token."""
    resp = client.post("/api/login", json={
        "email": "admin@servicenow.com",
        "password": "admin123",
    })
    return resp.json()["token"]


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
        assert "token" in data
        assert data["email"] == "admin@servicenow.com"
        assert data["role"] == "admin"

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
