"""
Authentication API routes — login, logout, and token validation.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from services.auth_service import generate_token, get_user_role, validate_credentials, verify_token
from utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["auth"])
logger = get_logger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str
    role: str
    message: str


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
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
async def verify(token: str = ""):
    """Verify a token is still valid."""
    result = verify_token(token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"valid": True, "email": result["email"], "role": result["role"]}
