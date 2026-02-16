"""
Config Tests — Tax Agent
=========================

Verify configuration loads correctly with defaults and env overrides.
"""
import os
import pytest


def test_config_defaults():
    """Config loads with sensible defaults"""
    from config import settings

    assert settings.database_name == "georgian_tax_db"
    assert settings.embedding_model == "text-embedding-004"
    assert settings.similarity_threshold == 0.5
    assert settings.matsne_request_delay == 2.0
    assert settings.search_limit == 5
    assert settings.rate_limit == 30
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.debug is False
    assert settings.require_api_key is False
    assert settings.api_key_max_per_ip == 10


def test_config_allowed_origins_default():
    """CORS origins default to localhost:3000"""
    from config import settings

    assert "http://localhost:3000" in settings.allowed_origins


def test_key_prefix():
    """Tax Agent keys use tk_ prefix (not Scoop's wk_)"""
    from app.auth.key_generator import KEY_PREFIX

    assert KEY_PREFIX == "tk_"


def test_key_generation():
    """Key generator produces valid tk_ keys"""
    from app.auth.key_generator import KeyGenerator

    result = KeyGenerator.generate("test-user")
    assert result.raw_key.startswith("tk_")
    assert len(result.raw_key) == 35  # tk_ + 32 hex chars
    assert result.user_id == "test-user"
    assert len(result.key_hash) == 64  # SHA-256 hex digest
    assert result.key_prefix == result.raw_key[:8]


def test_key_hash_deterministic():
    """Same key always produces same hash"""
    from app.auth.key_generator import KeyGenerator

    hash1 = KeyGenerator.hash_key("tk_abc123")
    hash2 = KeyGenerator.hash_key("tk_abc123")
    assert hash1 == hash2
