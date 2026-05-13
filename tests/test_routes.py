"""Integration tests for the auth API routes using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


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


# ── GET /api/verify ───────────────────────────────────────────────────

class TestVerifyEndpoint:
    def test_verify_valid_token(self, client):
        login_resp = client.post("/api/login", json={
            "email": "admin@servicenow.com",
            "password": "admin123",
        })
        token = login_resp.json()["token"]
        resp = client.get(f"/api/verify?token={token}")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True
        assert resp.json()["email"] == "admin@servicenow.com"

    def test_verify_invalid_token(self, client):
        resp = client.get("/api/verify?token=garbage")
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
