"""
Authentication service — handles login validation, token generation,
and token verification for the IM Dashboard.

Uses a simple JWT-like token approach with HMAC-SHA256.
In production, replace the mock user store with a real identity provider.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

from config.settings import settings

# Secret key derived from the SN password (in production, use a dedicated secret)
_SECRET = hashlib.sha256(settings.sn_password.encode()).hexdigest()

# Token validity: 8 hours
_TOKEN_EXPIRY_SECONDS = 8 * 3600

# Mock user credentials (email -> password hash)
# In production, validate against ServiceNow or an identity provider.
_MOCK_USERS: dict[str, str] = {
    "admin@servicenow.com": hashlib.sha256("admin123".encode()).hexdigest(),
    "im@servicenow.com": hashlib.sha256("incident2026".encode()).hexdigest(),
}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def validate_credentials(email: str, password: str) -> bool:
    """Check if email/password pair matches a known user."""
    stored_hash = _MOCK_USERS.get(email.lower())
    if not stored_hash:
        return False
    return hmac.compare_digest(stored_hash, _hash_password(password))


def generate_token(email: str) -> str:
    """Generate a signed token containing user email and expiry."""
    payload = json.dumps({
        "email": email.lower(),
        "exp": int(time.time()) + _TOKEN_EXPIRY_SECONDS,
    })
    signature = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Token format: base64-like payload.signature (simple encoding)
    import base64
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{signature}"


def verify_token(token: str) -> Optional[str]:
    """Verify token and return user email if valid, None otherwise."""
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
        return data.get("email")
    except Exception:
        return None
