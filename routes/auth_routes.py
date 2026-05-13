"""
Authentication API routes — login, logout, and token validation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.auth_service import generate_token, get_current_user, get_user_role, validate_credentials, verify_token
from utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["auth"])
logger = get_logger(__name__)
_limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str
    role: str
    message: str


@router.post("/login", response_model=LoginResponse)
@_limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest):
    """Authenticate user and return a session token."""
    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    if not validate_credentials(payload.email, payload.password):
        logger.warning("Failed login attempt for %s", payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = generate_token(payload.email)
    role = get_user_role(payload.email)
    logger.info("User %s logged in successfully (role=%s)", payload.email, role)
    return LoginResponse(token=token, email=payload.email, role=role, message="Login successful")


@router.post("/logout")
async def logout():
    """Logout endpoint — client should remove the token."""
    return {"message": "Logged out successfully"}


@router.get("/verify")
async def verify(user: dict = Depends(get_current_user)):
    """Verify the Bearer token is still valid."""
    return {"valid": True, "email": user["email"], "role": user["role"]}
