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
    assert settings.debug is False
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
    """Phase 2: Graph expansion defaults are safe (off, 5 refs, 20K chars).

    Note: MAX_CONTEXT_CHARS raised from 10k → 20k (Fix 2) for Georgian RAG coverage.
    """
    monkeypatch.delenv("GRAPH_EXPANSION_ENABLED", raising=False)
    monkeypatch.delenv("MAX_GRAPH_REFS", raising=False)
    monkeypatch.delenv("MAX_CONTEXT_CHARS", raising=False)
    from config import Settings

    s = Settings()
    assert s.graph_expansion_enabled is False
    assert s.max_graph_refs == 5
    assert s.max_context_chars == 20000


# =============================================================================
# Debug Flag Stress Tests
# =============================================================================


def test_debug_default_false_isolated(monkeypatch):
    """Debug defaults to False in isolation (production safety)."""
    monkeypatch.delenv("DEBUG", raising=False)
    from config import Settings

    s = Settings()
    assert s.debug is False


def test_debug_env_override_true(monkeypatch):
    """Debug activates when DEBUG=true is set in env."""
    monkeypatch.setenv("DEBUG", "true")
    from config import Settings

    s = Settings()
    assert s.debug is True


def test_debug_env_override_case_insensitive(monkeypatch):
    """Debug flag handles uppercase 'TRUE' correctly."""
    monkeypatch.setenv("DEBUG", "TRUE")
    from config import Settings

    s = Settings()
    assert s.debug is True


def test_debug_env_invalid_value(monkeypatch):
    """Pydantic v2 BaseSettings bool coercion: 'false'/'0'/'no'/'off' → False.
    Note: 'yes'/'on'/'1' are valid truthy values in Pydantic v2 bool parsing
    (unlike the old .lower() == 'true' pattern). Test uses explicit 'false'.
    """
    monkeypatch.setenv("DEBUG", "false")
    from config import Settings

    s = Settings()
    assert s.debug is False


# =============================================================================
# Fix 2 — Context Budget (TDD)
# =============================================================================


def test_max_context_chars_default_is_20000(monkeypatch):
    """Fix 2 — T-CB1: Default MAX_CONTEXT_CHARS must be 20000 (not 10000).

    Research basis: Georgian legal text ~2-3 chars/token for Gemini.
    10k chars ≈ 3,300–5,000 tokens → only 1-2 articles in context.
    20k chars ≈ 6,700–10,000 tokens → 8-9 articles (2× coverage, same latency).
    """
    monkeypatch.delenv("MAX_CONTEXT_CHARS", raising=False)
    from config import Settings

    s = Settings()
    assert s.max_context_chars == 20000, (
        f"Expected 20000 (Georgian RAG budget), got {s.max_context_chars}"
    )


def test_max_context_chars_env_override(monkeypatch):
    """Fix 2 — T-CB2: MAX_CONTEXT_CHARS env var override still works after fix."""
    monkeypatch.setenv("MAX_CONTEXT_CHARS", "30000")
    from config import Settings

    s = Settings()
    assert s.max_context_chars == 30000


# =============================================================================
# P1 — Pydantic V2 BaseSettings Migration (Sprint+1)
# =============================================================================


def test_settings_uses_basesettings():
    """P1: Settings must be an instance of BaseSettings, not plain BaseModel."""
    from pydantic_settings import BaseSettings
    from config import settings

    assert isinstance(settings, BaseSettings), (
        "Settings must inherit from pydantic_settings.BaseSettings for proper "
        "env var loading. Found: " + type(settings).__bases__[0].__name__
    )


def test_no_pydantic_v1_config_class():
    """P1: Settings must NOT have a nested Config class (Pydantic v1 pattern)."""
    from config import Settings

    assert not hasattr(Settings, "Config"), (
        "Settings still has a nested 'class Config' — Pydantic v1 pattern "
        "must be removed in favour of model_config = SettingsConfigDict(...)."
    )


def test_basesettings_reads_env_var(monkeypatch):
    """P1: BaseSettings must read an env var override without os.getenv()."""
    monkeypatch.setenv("SEARCH_LIMIT", "99")
    from config import Settings

    s = Settings()
    assert s.search_limit == 99, (
        f"Expected search_limit=99 from env var, got {s.search_limit}. "
        "BaseSettings env-var auto-reading is broken."
    )

