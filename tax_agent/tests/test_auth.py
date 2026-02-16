"""
Auth Tests — Tax Agent API Key Authentication
==============================================

Tests for:
- POST /auth/key (key generation)
- GET  /auth/key/verify (key verification)
- Auth dependencies (verify_api_key, verify_ownership)
- Edge cases and security invariants

These tests mock MongoDB to isolate auth logic from database state.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from httpx import AsyncClient, ASGITransport
from main import app


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key_store():
    """Mock the singleton api_key_store to avoid MongoDB dependency."""
    with patch("app.auth.router.api_key_store") as mock_store:
        mock_store.cleanup_stale_keys_by_ip = AsyncMock(return_value=0)
        mock_store.count_keys_by_ip = AsyncMock(return_value=0)
        mock_store.create_key = AsyncMock()
        mock_store.validate_key = AsyncMock(return_value=None)
        mock_store.touch = AsyncMock()
        yield mock_store


@pytest.fixture
def mock_verify_store():
    """Mock the api_key_store used in the /key/verify endpoint."""
    with patch("app.auth.router.api_key_store") as mock_store:
        mock_store.validate_key = AsyncMock(return_value=None)
        mock_store.touch = AsyncMock()
        yield mock_store


# ── POST /auth/key — Key Generation ─────────────────────────────────────


class TestKeyGeneration:
    """Tests for POST /auth/key endpoint."""

    @pytest.mark.asyncio
    async def test_generate_key_success(self, mock_api_key_store):
        """Should generate a key with tk_ prefix and return it."""
        from app.auth.key_generator import GeneratedKey

        mock_api_key_store.create_key.return_value = GeneratedKey(
            raw_key="tk_abc123def456",
            key_hash="hash_value",
            key_prefix="tk_abc12",
            user_id="user_42",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/auth/key", json={"user_id": "user_42"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["key"].startswith("tk_")
        assert data["user_id"] == "user_42"
        assert "expires_at" in data
        assert "key_prefix" in data

    @pytest.mark.asyncio
    async def test_generate_key_empty_user_id_rejected(self, mock_api_key_store):
        """Should reject empty user_id with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/auth/key", json={"user_id": ""})

        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_generate_key_missing_user_id_rejected(self, mock_api_key_store):
        """Should reject missing user_id with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/auth/key", json={})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_generate_key_rate_limit(self, mock_api_key_store):
        """Should return 429 when IP has too many keys."""
        mock_api_key_store.count_keys_by_ip.return_value = 999  # Over limit

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/auth/key", json={"user_id": "user_42"})

        assert resp.status_code == 429
        assert "Too many API keys" in resp.json()["detail"]


# ── GET /auth/key/verify — Key Verification ──────────────────────────────


class TestKeyVerification:
    """Tests for GET /auth/key/verify endpoint."""

    @pytest.mark.asyncio
    async def test_verify_key_missing_header(self, mock_verify_store):
        """Should return 400 when X-API-Key header is missing."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/auth/key/verify")

        assert resp.status_code == 400
        assert "X-API-Key header is required" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_verify_key_invalid(self, mock_verify_store):
        """Should return valid=false for an invalid key."""
        mock_verify_store.validate_key.return_value = None

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/auth/key/verify",
                headers={"X-API-Key": "tk_invalid"},
            )

        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_verify_key_valid(self, mock_verify_store):
        """Should return valid=true with user info for a valid key."""
        mock_verify_store.validate_key.return_value = {
            "key_hash": "hash",
            "user_id": "user_42",
            "key_prefix": "tk_abc12",
            "is_active": True,
            "expires_at": datetime.utcnow() + timedelta(days=30),
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/auth/key/verify",
                headers={"X-API-Key": "tk_valid_key_here"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["user_id"] == "user_42"

    @pytest.mark.asyncio
    async def test_verify_key_inactive(self, mock_verify_store):
        """Should return valid=false for a deactivated key."""
        mock_verify_store.validate_key.return_value = {
            "key_hash": "hash",
            "user_id": "user_42",
            "key_prefix": "tk_abc12",
            "is_active": False,  # Deactivated
            "expires_at": datetime.utcnow() + timedelta(days=30),
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/auth/key/verify",
                headers={"X-API-Key": "tk_deactivated"},
            )

        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_verify_key_expired(self, mock_verify_store):
        """Should return valid=false for an expired key."""
        mock_verify_store.validate_key.return_value = {
            "key_hash": "hash",
            "user_id": "user_42",
            "key_prefix": "tk_abc12",
            "is_active": True,
            "expires_at": datetime.utcnow() - timedelta(days=1),  # Expired
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/auth/key/verify",
                headers={"X-API-Key": "tk_expired"},
            )

        assert resp.status_code == 200
        assert resp.json()["valid"] is False


# ── Key Generator Security Invariants ────────────────────────────────────


class TestKeySecurityInvariants:
    """Security invariants for the key generation module."""

    def test_key_prefix_is_tk(self):
        """Keys MUST start with tk_ (not wk_ from Scoop)."""
        from app.auth.key_generator import KEY_PREFIX
        assert KEY_PREFIX == "tk_"

    def test_key_length_sufficient_entropy(self):
        """Generated keys must have sufficient entropy (>= 32 hex chars after prefix)."""
        from app.auth.key_generator import KeyGenerator
        generated = KeyGenerator.generate("test_user")
        raw_part = generated.raw_key.replace("tk_", "")
        assert len(raw_part) >= 32  # 128 bits minimum

    def test_hash_is_sha256(self):
        """Key hash must be SHA-256 (64 hex chars)."""
        from app.auth.key_generator import KeyGenerator
        generated = KeyGenerator.generate("test_user")
        assert len(generated.key_hash) == 64  # SHA-256 = 64 hex chars

    def test_two_keys_different(self):
        """Two generated keys for the same user must be different (CSPRNG)."""
        from app.auth.key_generator import KeyGenerator
        key1 = KeyGenerator.generate("same_user")
        key2 = KeyGenerator.generate("same_user")
        assert key1.raw_key != key2.raw_key
        assert key1.key_hash != key2.key_hash

    def test_hash_key_static_method_consistent(self):
        """hash_key() must produce the same hash for the same input."""
        from app.auth.key_generator import KeyGenerator
        raw = "tk_test123abc"
        h1 = KeyGenerator.hash_key(raw)
        h2 = KeyGenerator.hash_key(raw)
        assert h1 == h2
        assert len(h1) == 64


# ── Database Manager Unit Tests ──────────────────────────────────────────


class TestDatabaseManager:
    """Tests for the DatabaseManager singleton."""

    def test_singleton_instance(self):
        """DatabaseManager must be a singleton."""
        from app.database import DatabaseManager
        a = DatabaseManager()
        b = DatabaseManager()
        assert a is b

    def test_db_property_raises_without_connect(self):
        """Accessing db before connect() should raise RuntimeError."""
        from app.database import DatabaseManager
        manager = DatabaseManager()
        # Reset internal state for this test
        original_db = manager._db
        manager._db = None
        try:
            with pytest.raises(RuntimeError, match="Database not connected"):
                _ = manager.db
        finally:
            manager._db = original_db  # Restore


# ── CORS Configuration Test ──────────────────────────────────────────────


class TestCORSConfiguration:
    """Verify CORS middleware is correctly configured."""

    @pytest.mark.asyncio
    async def test_cors_allows_configured_origin(self):
        """CORS should allow the configured origin."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
        # CORS preflight should return 200
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers


# ── Rate Limit Handler Test ──────────────────────────────────────────────


class TestRateLimitHandler:
    """Verify the custom rate limit exception handler is registered."""

    @pytest.mark.asyncio
    async def test_rate_limit_handler_exists(self):
        """App should have a custom exception handler for RateLimitExceeded."""
        from slowapi.errors import RateLimitExceeded
        assert RateLimitExceeded in app.exception_handlers
