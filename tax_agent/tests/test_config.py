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
    assert settings.embedding_model == "gemini-embedding-001"
    assert settings.similarity_threshold == 0.5
    assert settings.matsne_request_delay == 2.0
    assert settings.search_limit == 5
    assert settings.rate_limit == 30
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.debug is True
    assert settings.require_api_key is False
    assert settings.api_key_max_per_ip == 10


def test_config_allowed_origins_default():
    """CORS origins default to localhost:3010"""
    from config import settings

    assert "http://localhost:3010" in settings.allowed_origins


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


# =============================================================================
# Feature Flag Tests (Step 1)
# =============================================================================


def test_flags_default_false(monkeypatch):
    """All orchestrator flags default to False when env vars not set."""
    monkeypatch.delenv("ROUTER_ENABLED", raising=False)
    monkeypatch.delenv("LOGIC_RULES_ENABLED", raising=False)
    monkeypatch.delenv("CRITIC_ENABLED", raising=False)
    from config import Settings

    s = Settings()
    assert s.router_enabled is False
    assert s.logic_rules_enabled is False
    assert s.critic_enabled is False


def test_flags_env_true(monkeypatch):
    """Flags activate when env vars set to 'true'."""
    monkeypatch.setenv("ROUTER_ENABLED", "true")
    monkeypatch.setenv("LOGIC_RULES_ENABLED", "true")
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    from config import Settings

    s = Settings()
    assert s.router_enabled is True
    assert s.logic_rules_enabled is True
    assert s.critic_enabled is True


def test_critic_threshold_default_07():
    """Critic confidence threshold defaults to 0.7."""
    from config import Settings

    s = Settings()
    assert s.critic_confidence_threshold == 0.7


def test_critic_threshold_custom(monkeypatch):
    """Critic threshold reads custom value from env."""
    monkeypatch.setenv("CRITIC_CONFIDENCE_THRESHOLD", "0.85")
    from config import Settings

    s = Settings()
    assert s.critic_confidence_threshold == 0.85


# =============================================================================
# Phase 2: Graph Expansion Config Tests
# =============================================================================


def test_config_graph_defaults(monkeypatch):
    """Phase 2: Graph expansion defaults are safe (off, 5 refs, 10K chars)."""
    monkeypatch.delenv("GRAPH_EXPANSION_ENABLED", raising=False)
    monkeypatch.delenv("MAX_GRAPH_REFS", raising=False)
    monkeypatch.delenv("MAX_CONTEXT_CHARS", raising=False)
    from config import Settings

    s = Settings()
    assert s.graph_expansion_enabled is False
    assert s.max_graph_refs == 5
    assert s.max_context_chars == 10000

