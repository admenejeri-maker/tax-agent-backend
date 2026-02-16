"""
API Key Store — Tax Agent Authentication
=========================================

MongoDB CRUD operations for the `api_keys` collection.
Handles key creation (concurrent-safe upsert), validation, and touch.

Adapted from Scoop backend/app/auth/api_key_store.py
Changes: import paths updated, stdlib logging → structlog.

Security notes:
- All stored keys are SHA-256 hashed (raw key NEVER persisted)
- `secrets.compare_digest()` for timing-safe hash comparison
- Upsert on user_id prevents duplicate keys from concurrent requests
"""

import hashlib
import secrets
import structlog
from datetime import datetime, timedelta
from typing import Optional

from app.auth.key_generator import KeyGenerator, GeneratedKey
from app.database import db_manager

logger = structlog.get_logger(__name__)

# Default key TTL: 365 days
DEFAULT_KEY_TTL_DAYS = 365

# Stale key cleanup: keys unused for this many hours are auto-deleted
STALE_KEY_THRESHOLD_HOURS = 2


class APIKeyStore:
    """MongoDB CRUD for the api_keys collection."""

    @property
    def _collection(self):
        """Get the api_keys collection from the database manager."""
        return db_manager.db.api_keys

    async def create_key(
        self,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> GeneratedKey:
        """
        Create a new API key for a user_id.

        Uses concurrent-safe upsert: if a key already exists for this user_id,
        returns a freshly generated key (replaces the old one).

        Args:
            user_id: The user_id to associate with this key.
            ip_address: Client IP for privacy-aware logging (hashed).
            user_agent: Client User-Agent string.
            origin: Request Origin header.

        Returns:
            GeneratedKey with the raw key to return to the client.
        """
        generated = KeyGenerator.generate(user_id)
        now = datetime.utcnow()

        # Hash IP for privacy-aware logging
        ip_hash = (
            hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
            if ip_address
            else None
        )

        document = {
            "key_hash": generated.key_hash,
            "key_prefix": generated.key_prefix,
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + timedelta(days=DEFAULT_KEY_TTL_DAYS),
            "last_used_at": now,
            "is_active": True,
            "rate_limit_tier": "standard",
            "metadata": {
                "user_agent": user_agent,
                "origin": origin,
                "ip_hash": ip_hash,
            },
        }

        # Concurrent-safe upsert: filter by user_id, replace entire document
        await self._collection.update_one(
            {"user_id": user_id},
            {"$set": document},
            upsert=True,
        )

        logger.info(
            "api_key_created",
            user_id=user_id,
            key_prefix=generated.key_prefix,
        )
        return generated

    async def find_by_hash(self, key_hash: str) -> Optional[dict]:
        """
        Find a key document by its SHA-256 hash.

        Args:
            key_hash: SHA-256 hex digest of the raw key.

        Returns:
            Key document dict or None if not found.
        """
        return await self._collection.find_one({"key_hash": key_hash})

    async def validate_key(self, raw_key: str) -> Optional[dict]:
        """
        Validate a raw API key with timing-safe comparison.

        Args:
            raw_key: The full API key from X-API-Key header.

        Returns:
            Key document dict if valid, None if invalid.
        """
        key_hash = KeyGenerator.hash_key(raw_key)
        key_doc = await self.find_by_hash(key_hash)

        if key_doc is None:
            return None

        # Timing-safe comparison to prevent timing attacks
        if not secrets.compare_digest(key_doc["key_hash"], key_hash):
            return None

        return key_doc

    async def touch(self, key_hash: str) -> None:
        """
        Update last_used_at timestamp for a key (fire-and-forget).

        Args:
            key_hash: SHA-256 hex digest of the key.
        """
        try:
            await self._collection.update_one(
                {"key_hash": key_hash},
                {"$set": {"last_used_at": datetime.utcnow()}},
            )
        except Exception as e:
            logger.warning("api_key_touch_failed", error=str(e))

    async def deactivate_key(self, user_id: str) -> bool:
        """
        Deactivate all keys for a user_id (soft delete).

        Args:
            user_id: The user_id whose keys should be deactivated.

        Returns:
            True if any keys were deactivated.
        """
        result = await self._collection.update_many(
            {"user_id": user_id, "is_active": True},
            {"$set": {"is_active": False}},
        )
        if result.modified_count > 0:
            logger.info("api_keys_deactivated", user_id=user_id, count=result.modified_count)
        return result.modified_count > 0

    async def count_keys_by_ip(self, ip_address: str) -> int:
        """
        Count active keys created from a given IP address.

        Args:
            ip_address: Client IP address (will be hashed for lookup).

        Returns:
            Count of active keys from this IP.
        """
        ip_hash = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
        return await self._collection.count_documents(
            {"metadata.ip_hash": ip_hash, "is_active": True}
        )

    async def cleanup_stale_keys_by_ip(self, ip_address: str) -> int:
        """
        Delete stale keys (unused for STALE_KEY_THRESHOLD_HOURS) from a given IP.

        Args:
            ip_address: Client IP address (will be hashed for lookup).

        Returns:
            Number of stale keys deleted.
        """
        ip_hash = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
        cutoff = datetime.utcnow() - timedelta(hours=STALE_KEY_THRESHOLD_HOURS)

        result = await self._collection.delete_many({
            "metadata.ip_hash": ip_hash,
            "last_used_at": {"$lt": cutoff},
        })

        if result.deleted_count > 0:
            logger.info(
                "stale_keys_cleaned",
                ip_prefix=ip_address[:8],
                count=result.deleted_count,
            )
        return result.deleted_count


# Singleton instance
api_key_store = APIKeyStore()
