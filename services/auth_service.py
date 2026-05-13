"""
Authentication service — handles login validation, token generation,
and token verification for the IM Dashboard.

User credentials are loaded from the AUTH_USERS environment variable.
Passwords are hashed with bcrypt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)

# Dedicated JWT secret from environment; falls back to a derived value if not set
if settings.jwt_secret:
    _SECRET = settings.jwt_secret
else:
    log.warning("JWT_SECRET not set — falling back to derived secret. Set JWT_SECRET in .env for production.")
    _SECRET = hashlib.sha256(settings.sn_password.encode()).hexdigest()

# Token validity: 8 hours
_TOKEN_EXPIRY_SECONDS = 8 * 3600


def _load_users() -> dict[str, dict[str, str]]:
    """Parse AUTH_USERS env var into a user dict.

    Format: email1:bcrypt_hash1:role1|email2:bcrypt_hash2:role2|...
    """
    users: dict[str, dict[str, str]] = {}
    raw = settings.auth_users.strip()
    if not raw:
        log.warning("AUTH_USERS is empty — no dashboard users configured")
        return users
    for entry in raw.split("|"):
        parts = entry.strip().split(":", 2)
        if len(parts) != 3:
            log.warning("Skipping malformed AUTH_USERS entry: %s", entry)
            continue
        email, pw_hash, role = parts
        users[email.lower()] = {"password_hash": pw_hash, "role": role}
    log.info("Loaded %d dashboard user(s) from AUTH_USERS", len(users))
    return users


_USERS = _load_users()


def validate_credentials(email: str, password: str) -> bool:
    """Check if email/password pair matches a known user using bcrypt."""
    user = _USERS.get(email.lower())
    if not user:
        return False
    try:
        return bcrypt.checkpw(password.encode(), user["password_hash"].encode())
    except (ValueError, TypeError):
        log.exception("bcrypt verification failed for %s", email)
        return False


def get_user_role(email: str) -> str:
    """Return the role for the given user email."""
    user = _USERS.get(email.lower())
    return user["role"] if user else "readonly"


def generate_token(email: str) -> str:
    """Generate a signed token containing user email, role, and expiry."""
    role = get_user_role(email)
    payload = json.dumps({
        "email": email.lower(),
        "role": role,
        "exp": int(time.time()) + _TOKEN_EXPIRY_SECONDS,
    })
    signature = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Token format: base64-like payload.signature (simple encoding)
    import base64
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{signature}"


def verify_token(token: str) -> Optional[dict]:
    """Verify token and return {email, role} dict if valid, None otherwise."""
    import base64
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        encoded, signature = parts
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
        expected_sig = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return {"email": data.get("email"), "role": data.get("role", "readonly")}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependency — extracts & validates the Bearer token or cookie
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)
_COOKIE_NAME = "im_auth_token"


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency that extracts and verifies the auth token.

    Checks (in order):
        1. Authorization: Bearer <token> header
        2. im_auth_token httpOnly cookie

    Returns ``{"email": ..., "role": ...}`` on success, raises 401 otherwise.
    """
    token: str | None = None

    # Prefer Authorization header (for programmatic clients)
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        # Fall back to httpOnly cookie (browser sessions)
        token = request.cookies.get(_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    user = verify_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


# ---------------------------------------------------------------------------
# Role-based authorization dependencies
# ---------------------------------------------------------------------------

# Roles with write access (can create/update/delete dashboard data)
_WRITE_ROLES = {"admin", "manager", "incident_manager"}


def require_write_access(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency that enforces write (mutating) access.

    Only users with admin, manager, or incident_manager roles can
    create, update, or delete dashboard records. Readonly users are blocked.
    """
    role = user.get("role", "readonly")
    if role not in _WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' does not have write access",
        )
    return user
