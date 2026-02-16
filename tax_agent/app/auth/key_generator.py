"""
API Key Generator — Tax Agent Authentication
=============================================

Generates cryptographically secure API keys with SHA-256 hashing.
Keys follow the format: tk_<32-char-hex> (tax key prefix).

Adapted from Scoop backend/app/auth/key_generator.py
Changes: wk_ → tk_ prefix for service differentiation.

Security notes:
- Uses `secrets` module (CSPRNG) for key generation
- SHA-256 hash stored in MongoDB, raw key NEVER persisted
- `key_prefix` (first 8 chars) stored for admin identification
"""

import hashlib
import secrets
from dataclasses import dataclass


# Key format: "tk_" prefix + 32 hex characters = 35 chars total
KEY_PREFIX = "tk_"
KEY_BYTES = 16  # 16 bytes = 32 hex chars = 128 bits of entropy


@dataclass(frozen=True)
class GeneratedKey:
    """Immutable result of key generation."""
    raw_key: str       # Full key to return to client (e.g., "tk_a3f2b1c4...")
    key_hash: str      # SHA-256 hash to store in MongoDB
    key_prefix: str    # First 8 chars for admin identification
    user_id: str       # Associated user_id


class KeyGenerator:
    """Generates cryptographically secure API keys."""

    @staticmethod
    def generate(user_id: str) -> GeneratedKey:
        """
        Generate a new API key for a given user_id.

        Args:
            user_id: The user_id to associate with this key.

        Returns:
            GeneratedKey with raw_key, key_hash, key_prefix, and user_id.
        """
        # Generate cryptographically secure random bytes
        random_hex = secrets.token_hex(KEY_BYTES)
        raw_key = f"{KEY_PREFIX}{random_hex}"

        # Hash for storage — NEVER store the raw key
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        # Prefix for admin logs (first 8 chars of full key)
        key_prefix = raw_key[:8]

        return GeneratedKey(
            raw_key=raw_key,
            key_hash=key_hash,
            key_prefix=key_prefix,
            user_id=user_id,
        )

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """
        Hash a raw API key for lookup.

        Args:
            raw_key: The full API key from X-API-Key header.

        Returns:
            SHA-256 hex digest of the key.
        """
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
