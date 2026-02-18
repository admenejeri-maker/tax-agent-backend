"""
Configuration for Georgian Tax AI Agent
Adapted from Scoop AI backend config.py — "Copy-Adapt" strategy
"""
import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


def _safe_float(env_var: str, default: float) -> float:
    """Parse float env var with fallback — never crash at import time."""
    try:
        return float(os.getenv(env_var, str(default)))
    except (ValueError, TypeError):
        return default


class Settings(BaseModel):
    """Tax Agent application settings with production defaults"""

    # =========================================================================
    # MongoDB
    # =========================================================================
    mongodb_uri: str = Field(default_factory=lambda: os.getenv("MONGODB_URI", ""))
    database_name: str = Field(
        default_factory=lambda: os.getenv("DATABASE_NAME", "georgian_tax_db")
    )

    # =========================================================================
    # Google AI
    # =========================================================================
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    embedding_model: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    )

    # =========================================================================
    # LLM Generation (RAG Pipeline)
    # =========================================================================
    generation_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_GENERATION_MODEL", "gemini-3-flash-preview")
    )
    temperature: float = Field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2"))
    )
    max_history_turns: int = Field(
        default_factory=lambda: int(os.getenv("MAX_HISTORY_TURNS", "5"))
    )
    max_output_tokens: int = Field(
        default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))
    )
    query_rewrite_model: str = Field(
        default_factory=lambda: os.getenv("QUERY_REWRITE_MODEL", "gemini-3-flash-preview")
    )
    query_rewrite_timeout: float = Field(
        default_factory=lambda: float(os.getenv("QUERY_REWRITE_TIMEOUT", "3.0"))
    )

    # =========================================================================
    # Tax Agent Settings
    # =========================================================================
    similarity_threshold: float = Field(
        default_factory=lambda: float(os.getenv("SIMILARITY_THRESHOLD", "0.5"))
    )
    matsne_request_delay: float = Field(
        default_factory=lambda: float(os.getenv("MATSNE_REQUEST_DELAY", "2.0"))
    )
    search_limit: int = Field(
        default_factory=lambda: int(os.getenv("SEARCH_LIMIT", "5"))
    )
    keyword_search_enabled: bool = Field(
        default_factory=lambda: os.getenv("KEYWORD_SEARCH_ENABLED", "true").lower() == "true"
    )

    # =========================================================================
    # Feature Flags (Orchestrator) — all default to False for safe rollout
    # =========================================================================
    router_enabled: bool = Field(
        default_factory=lambda: os.getenv("ROUTER_ENABLED", "false").lower() == "true"
    )
    logic_rules_enabled: bool = Field(
        default_factory=lambda: os.getenv("LOGIC_RULES_ENABLED", "false").lower() == "true"
    )
    critic_enabled: bool = Field(
        default_factory=lambda: os.getenv("CRITIC_ENABLED", "false").lower() == "true"
    )
    critic_confidence_threshold: float = Field(
        default_factory=lambda: _safe_float("CRITIC_CONFIDENCE_THRESHOLD", 0.7)
    )
    critic_regeneration_enabled: bool = Field(
        default_factory=lambda: os.getenv("CRITIC_REGENERATION_ENABLED", "false").lower() == "true"
    )

    # =========================================================================
    # Safety & Truncation Defense
    # =========================================================================
    safety_retry_enabled: bool = Field(
        default_factory=lambda: os.getenv("SAFETY_RETRY_ENABLED", "true").lower() == "true"
    )
    safety_fallback_model: str = Field(
        default_factory=lambda: os.getenv("SAFETY_FALLBACK_MODEL", "gemini-2.5-flash")
    )

    # =========================================================================
    # Citation / Grounded UI (Task 7)
    # =========================================================================
    citation_enabled: bool = Field(
        default_factory=lambda: os.getenv("CITATION_ENABLED", "true").lower() == "true"
    )
    matsne_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "MATSNE_BASE_URL",
            "https://matsne.gov.ge/ka/document/view/1043717/most-current-version",
        )
    )

    # =========================================================================
    # Authentication
    # =========================================================================
    api_key_secret: str = Field(
        default_factory=lambda: os.getenv("API_KEY_SECRET", "")
    )
    require_api_key: bool = Field(
        default_factory=lambda: os.getenv("REQUIRE_API_KEY", "false").lower() == "true"
    )
    api_key_max_per_ip: int = Field(
        default_factory=lambda: int(os.getenv("API_KEY_MAX_PER_IP", "10"))
    )

    # =========================================================================
    # Server
    # =========================================================================
    host: str = "0.0.0.0"
    port: int = Field(
        default_factory=lambda: int(os.getenv("PORT", "8000"))
    )
    debug: bool = Field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )
    rate_limit: int = Field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT", "30"))
    )
    allowed_origins: str = Field(
        default_factory=lambda: os.getenv("ALLOWED_ORIGINS", "http://localhost:3010")
    )

    class Config:
        env_file = ".env"


settings = Settings()
