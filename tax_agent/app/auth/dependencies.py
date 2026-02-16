"""
Auth Dependencies — Tax Agent Authentication
=============================================

FastAPI Depends() functions for API key verification.

Two verifiers (simplified from Scoop — no SSE or session ownership needed):
1. verify_api_key     — Validates key, checks expiry, returns key_doc
2. verify_ownership   — Ensures key's user_id matches path param user_id (IDOR fix)

Adapted from Scoop backend/app/auth/dependencies.py
Changes: import paths, structlog, removed verify_session_ownership + SSE fallback.

Usage:
    @app.post("/query")
    async def query(request: QueryRequest, key_doc: dict = Depends(verify_api_key)):
        user_id = key_doc["user_id"]  # Trusted, not client-supplied

Security notes:
- Feature flag: REQUIRE_API_KEY=false → auth is optional (migration mode)
- When optional, missing key is allowed but valid key is still validated
"""

import structlog
from datetime import datetime
from typing import Optional

from fastapi import Header, HTTPException, Depends, Request

from app.auth.api_key_store import api_key_store
from app.auth.key_generator import KeyGenerator

logger = structlog.get_logger(__name__)


async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
) -> Optional[dict]:
    """
    Verify API key from X-API-Key header.

    Behavior depends on REQUIRE_API_KEY feature flag:
    - True:  key is mandatory → 401 if missing/invalid
    - False: key is optional → None if missing, but validated if present

    Returns:
        Key document dict with user_id, or None if key is optional and missing.

    Raises:
        HTTPException 401: Key required but missing, or key invalid/expired.
        HTTPException 403: Key is revoked.
    """
    # Import here to avoid circular import with config
    from config import settings

    require_key = settings.require_api_key

    # No key provided
    if not x_api_key:
        if require_key:
            raise HTTPException(
                status_code=401,
                detail="API key required. Send X-API-Key header.",
            )
        return None  # Optional mode: allow unauthenticated access

    # Validate key
    key_doc = await api_key_store.validate_key(x_api_key)

    if key_doc is None:
        key_prefix = x_api_key[:8] if len(x_api_key) >= 8 else x_api_key[:4] + "..."
        logger.warning(
            "api_key_validation_failed",
            key_prefix=key_prefix,
            key_length=len(x_api_key),
            path=request.url.path,
        )
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check active status
    if not key_doc.get("is_active"):
        raise HTTPException(status_code=403, detail="API key revoked")

    # Check expiration
    expires_at = key_doc.get("expires_at")
    if expires_at and expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key expired")

    # Update last_used_at (fire-and-forget)
    key_hash = KeyGenerator.hash_key(x_api_key)
    await api_key_store.touch(key_hash)

    logger.debug(
        "api_key_validated",
        key_prefix=key_doc.get("key_prefix", "N/A"),
        user_id=key_doc.get("user_id", "N/A"),
        path=request.url.path,
    )

    return key_doc


async def verify_ownership(
    user_id: str,
    key_doc: Optional[dict] = Depends(verify_api_key),
) -> Optional[dict]:
    """
    Verify the API key owner matches the requested user_id (path param).

    Prevents IDOR: user A's key cannot access user B's data.

    Args:
        user_id: Path parameter (e.g., /conversations/{user_id}).
        key_doc: Result from verify_api_key dependency.

    Returns:
        Key document dict if ownership verified, None if auth is optional.

    Raises:
        HTTPException 403: Key's user_id doesn't match path user_id.
    """
    if key_doc is None:
        return None  # Auth is optional and no key provided

    if key_doc["user_id"] != user_id:
        logger.warning(
            "idor_attempt",
            key_user=key_doc["user_id"],
            target_user=user_id,
        )
        raise HTTPException(status_code=403, detail="Access denied")

    return key_doc
