"""
Configuration for Georgian Tax AI Agent
Adapted from Scoop AI backend config.py — "Copy-Adapt" strategy

Pydantic v2 — uses BaseSettings from pydantic-settings for proper
env var loading without manual os.getenv() lambdas.
"""
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# load_dotenv() kept for backward compat (ensures .env is loaded into os.environ
# before any other module imports; BaseSettings will also read it via env_file).
load_dotenv()


class Settings(BaseSettings):
    """Tax Agent application settings with production defaults.

    BaseSettings automatically reads env vars by field name (case-insensitive).
    Example: field `gemini_api_key` reads from env var `GEMINI_API_KEY`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # =========================================================================
    # MongoDB
    # =========================================================================
    mongodb_uri: str = Field(default="")
    database_name: str = Field(default="georgian_tax_db")

    # =========================================================================
    # Google AI
    # =========================================================================
    gemini_api_key: str = Field(default="")

    embedding_model: str = Field(default="gemini-embedding-001")

    # =========================================================================
    # LLM Generation (RAG Pipeline)
    # =========================================================================
    generation_model: str = Field(
        default="gemini-3-flash-preview",
        alias="gemini_generation_model",
        validation_alias="GEMINI_GENERATION_MODEL",
    )

    temperature: float = Field(default=0.2)
    max_history_turns: int = Field(default=5)
    max_output_tokens: int = Field(default=8192)
    query_rewrite_model: str = Field(default="gemini-3-flash-preview")
    query_rewrite_timeout: float = Field(default=3.0)

    # =========================================================================
    # Tax Agent Settings
    # =========================================================================
    similarity_threshold: float = Field(default=0.5)
    matsne_request_delay: float = Field(default=2.0)
    search_limit: int = Field(default=5)
    keyword_search_enabled: bool = Field(default=True)

    # =========================================================================
    # Feature Flags (Orchestrator) — all default to False for safe rollout
    # =========================================================================
    router_enabled: bool = Field(default=False)
    logic_rules_enabled: bool = Field(default=False)
    critic_enabled: bool = Field(default=False)
    critic_confidence_threshold: float = Field(default=0.7)
    critic_regeneration_enabled: bool = Field(default=False)

    # ── Graph Expansion (Phase 2 MVP) ──
    graph_expansion_enabled: bool = Field(default=False)
    max_graph_refs: int = Field(default=5)
    max_context_chars: int = Field(default=20000)

    # ── Follow-Up Suggestions (Phase 1: Quick Replies) ──
    follow_up_enabled: bool = Field(default=True)
    follow_up_model: str = Field(default="gemini-2.0-flash")
    follow_up_max_suggestions: int = Field(default=4)
    follow_up_timeout: float = Field(default=5.0)

    # =========================================================================
    # Safety & Truncation Defense
    # =========================================================================
    safety_retry_enabled: bool = Field(default=True)
    safety_fallback_model: str = Field(default="gemini-2.5-flash")

    # =========================================================================
    # Citation / Grounded UI (Task 7)
    # =========================================================================
    citation_enabled: bool = Field(default=True)
    matsne_base_url: str = Field(
        default="https://matsne.gov.ge/ka/document/view/1043717/most-current-version"
    )

    # =========================================================================
    # Authentication
    # =========================================================================
    api_key_secret: str = Field(default="")
    require_api_key: bool = Field(default=False)
    api_key_max_per_ip: int = Field(default=10)

    # =========================================================================
    # Server
    # =========================================================================
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    rate_limit: int = Field(default=30)
    allowed_origins: str = Field(default="http://localhost:3010")


settings = Settings()
