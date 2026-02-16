"""
Auth Router — Tax Agent API Key Authentication
===============================================

Endpoints:
- POST /auth/key        → Generate a new API key for a user_id
- GET  /auth/key/verify → Verify an existing API key is valid

Adapted from Scoop backend/app/auth/router.py
Changes: import paths, structlog, tk_ key format in docs.

Rate limiting: IP-based limit on key generation (prevents abuse).
Feature flag: REQUIRE_API_KEY controls enforcement in dependencies.
"""

import structlog
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel, Field

from config import settings
from app.auth.api_key_store import api_key_store
from app.auth.key_generator import KeyGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Authentication"])


# ── Request / Response Models ──────────────────────────────────────────

class KeyGenerateRequest(BaseModel):
    """Request body for key generation."""
    user_id: str = Field(..., min_length=1, max_length=128, description="User ID")


class KeyGenerateResponse(BaseModel):
    """Response from key generation — contains the raw key (shown ONCE)."""
    key: str = Field(..., description="The API key (tk_... format). Store it — not shown again.")
    user_id: str
    expires_at: str = Field(..., description="ISO 8601 expiry timestamp")
    key_prefix: str = Field(..., description="First 8 chars for identification")


class KeyVerifyResponse(BaseModel):
    """Response from key verification."""
    valid: bool
    user_id: Optional[str] = None
    key_prefix: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/key", response_model=KeyGenerateResponse)
async def generate_key(body: KeyGenerateRequest, request: Request):
    """
    Generate a new API key for a user.

    - Rate limited by IP (max `API_KEY_MAX_PER_IP` active keys per IP)
    - Idempotent: if user_id already has a key, it is replaced (upsert)
    - Raw key is returned ONCE — only the hash is stored in MongoDB
    """
    ip_address = request.client.host if request.client else "unknown"

    # Clean up stale keys before rate limiting
    await api_key_store.cleanup_stale_keys_by_ip(ip_address)

    # IP-based rate limit on key generation
    ip_key_count = await api_key_store.count_keys_by_ip(ip_address)
    if ip_key_count >= settings.api_key_max_per_ip:
        logger.warning(
            "key_generation_rate_limit",
            ip_prefix=ip_address[:8],
            key_count=ip_key_count,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many API keys from this IP. Max: {settings.api_key_max_per_ip}",
        )

    # Generate and store the key
    generated = await api_key_store.create_key(
        user_id=body.user_id,
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
        origin=request.headers.get("origin"),
    )

    return KeyGenerateResponse(
        key=generated.raw_key,
        user_id=generated.user_id,
        expires_at=str(
            datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        ),
        key_prefix=generated.key_prefix,
    )


@router.get("/key/verify", response_model=KeyVerifyResponse)
async def verify_key(x_api_key: Optional[str] = Header(None)):
    """
    Verify an API key is valid.

    Send the key in the `X-API-Key` header.
    Returns validity status and associated user info.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=400,
            detail="X-API-Key header is required for verification.",
        )

    key_doc = await api_key_store.validate_key(x_api_key)

    if key_doc is None:
        return KeyVerifyResponse(valid=False)

    # Check active status
    if not key_doc.get("is_active", False):
        return KeyVerifyResponse(valid=False)

    # Check expiry
    expires_at = key_doc.get("expires_at")
    if expires_at and expires_at < datetime.utcnow():
        return KeyVerifyResponse(valid=False)

    # Touch (update last_used_at) — fire-and-forget
    await api_key_store.touch(key_doc["key_hash"])

    return KeyVerifyResponse(
        valid=True,
        user_id=key_doc.get("user_id"),
        key_prefix=key_doc.get("key_prefix"),
    )
