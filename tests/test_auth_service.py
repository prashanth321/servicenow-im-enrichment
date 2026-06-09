"""Unit tests for the authentication service."""

import time

import bcrypt
import pytest

from services.auth_service import (
    _load_users,
    _SECRET,
    generate_token,
    get_user_role,
    validate_credentials,
    verify_token,
)
from config.settings import settings


# ── validate_credentials ──────────────────────────────────────────────

class TestValidateCredentials:
    def test_valid_admin_login(self):
        assert validate_credentials("admin@servicenow.com", "admin123") is True

    def test_valid_im_login(self):
        assert validate_credentials("im@servicenow.com", "incident2026") is True

    def test_valid_readonly_login(self):
        assert validate_credentials("readonly@servicenow.com", "readonly123") is True

    def test_wrong_password(self):
        assert validate_credentials("admin@servicenow.com", "wrongpassword") is False

    def test_unknown_user(self):
        assert validate_credentials("nobody@example.com", "password") is False

    def test_case_insensitive_email(self):
        assert validate_credentials("ADMIN@SERVICENOW.COM", "admin123") is True

    def test_empty_email(self):
        assert validate_credentials("", "admin123") is False

    def test_empty_password(self):
        assert validate_credentials("admin@servicenow.com", "") is False


# ── get_user_role ─────────────────────────────────────────────────────

class TestGetUserRole:
    def test_admin_role(self):
        assert get_user_role("admin@servicenow.com") == "admin"

    def test_readonly_role(self):
        assert get_user_role("readonly@servicenow.com") == "readonly"

    def test_unknown_user_defaults_readonly(self):
        assert get_user_role("unknown@example.com") == "readonly"


# ── generate_token / verify_token ─────────────────────────────────────

class TestTokens:
    def test_generate_and_verify(self):
        token = generate_token("admin@servicenow.com")
        result = verify_token(token)
        assert result is not None
        assert result["email"] == "admin@servicenow.com"
        assert result["role"] == "admin"

    def test_token_contains_dot_separator(self):
        token = generate_token("admin@servicenow.com")
        assert "." in token

    def test_tampered_token_rejected(self):
        token = generate_token("admin@servicenow.com")
        tampered = token[:-4] + "XXXX"
        assert verify_token(tampered) is None

    def test_garbage_token_rejected(self):
        assert verify_token("not.a.valid.token") is None
        assert verify_token("") is None
        assert verify_token("onlyonepart") is None

    def test_token_role_matches(self):
        token = generate_token("readonly@servicenow.com")
        result = verify_token(token)
        assert result["role"] == "readonly"


# ── _load_users ───────────────────────────────────────────────────────

class TestLoadUsers:
    def test_loads_users_from_env(self):
        users = _load_users()
        assert len(users) >= 1
        for email, data in users.items():
            assert "password_hash" in data
            assert "role" in data
            assert data["role"] in ("admin", "readonly")


# ── JWT secret isolation ──────────────────────────────────────────────

class TestJwtSecret:
    def test_jwt_secret_is_from_env(self):
        if settings.jwt_secret:
            assert _SECRET == settings.jwt_secret
        # If JWT_SECRET is not set, it falls back to derived — still valid
