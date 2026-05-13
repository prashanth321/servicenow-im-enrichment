"""
Authentication API routes — login, logout, and token validation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.auth_service import generate_token, get_current_user, get_user_role, validate_credentials, verify_token
from utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["auth"])
logger = get_logger(__name__)
_limiter = Limiter(key_func=get_remote_address)

# Cookie configuration
_COOKIE_NAME = "im_auth_token"
_COOKIE_MAX_AGE = 8 * 3600  # Match token expiry


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    email: str
    role: str
    message: str


@router.post("/login", response_model=LoginResponse)
@_limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest):
    """Authenticate user and return a session token via httpOnly cookie."""
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    if not validate_credentials(payload.email, payload.password):
        logger.warning("Failed login attempt for %s", payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = generate_token(payload.email)
    role = get_user_role(payload.email)
    logger.info("User %s logged in successfully (role=%s)", payload.email, role)

    response = JSONResponse(content={
        "email": payload.email,
        "role": role,
        "message": "Login successful",
    })
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,  # Set True when served over HTTPS
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    """Logout endpoint — clear the auth cookie."""
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(key=_COOKIE_NAME, path="/")
    return response


@router.get("/verify")
async def verify(user: dict = Depends(get_current_user)):
    """Verify the auth token (cookie or Bearer) is still valid."""
    return {"valid": True, "email": user["email"], "role": user["role"]}
