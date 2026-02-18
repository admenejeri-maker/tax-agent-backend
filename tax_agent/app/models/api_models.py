"""
API Request/Response Models — Task 7
=====================================

Pydantic models for API endpoint validation.
Maps RAGResponse fields to client-facing schema.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Request Models ───────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """Request body for POST /api/ask and /api/ask/stream."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Question about Georgian tax law",
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Resume an existing conversation (omit to start new)",
    )

    @field_validator("question")
    @classmethod
    def strip_and_validate(cls, v: str) -> str:
        """Strip whitespace and reject empty-after-strip questions."""
        v = v.strip()
        if not v:
            raise ValueError("Question cannot be empty or just whitespace")
        return v


class ClearRequest(BaseModel):
    """Request body for POST /api/session/clear."""

    conversation_id: str = Field(
        ...,
        description="Session to clear",
    )


# ─── Response Models ──────────────────────────────────────────────────────────


class SourceDetail(BaseModel):
    """Source metadata in API response (mapped from SourceMetadata)."""

    id: int = 0  # Sequential citation ID (1, 2, 3...)
    article_number: Optional[str] = None
    chapter: Optional[str] = None
    title: Optional[str] = None
    score: float = 0.0
    url: Optional[str] = None  # Matsne deep-link
    text: Optional[str] = None  # Source chunk body


class AskResponse(BaseModel):
    """Response from POST /api/ask.

    Field mapping from RAGResponse:
        answer           ← rag.answer
        sources          ← rag.source_metadata (as SourceDetail list)
        disclaimer       ← rag.disclaimer (Optional[str])
        temporal_warning ← rag.temporal_warning (Optional[str])
        confidence_score ← rag.confidence_score
        conversation_id  ← session_id (from ConversationStore)
    """

    answer: str
    sources: List[SourceDetail] = Field(default_factory=list)
    disclaimer: Optional[str] = None
    temporal_warning: Optional[str] = None
    confidence_score: float = 0.0
    conversation_id: str


class ArticleResponse(BaseModel):
    """Response from GET /api/articles/{number}."""

    article_number: int
    title_ka: Optional[str] = None
    title_en: Optional[str] = None
    body_ka: Optional[str] = None
    body_en: Optional[str] = None
    kari: Optional[str] = None
    tavi: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standardized error response."""

    error: str
    code: str  # INVALID_INPUT | RATE_LIMITED | LLM_ERROR | DB_ERROR | NOT_FOUND


class SessionListItem(BaseModel):
    """One item in the sessions list response."""

    conversation_id: str
    title: str
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    turn_count: int = 0


class SessionHistoryResponse(BaseModel):
    """Response from GET /api/session/{id}/history."""

    conversation_id: str
    title: str
    turns: List[dict] = Field(default_factory=list)


class ClearResponse(BaseModel):
    """Response from POST /api/session/clear."""

    cleared: bool


class HealthResponse(BaseModel):
    """Response from GET /api/health."""

    status: str
    db_connected: bool
    articles_count: int = 0
    version: str = "1.0.0"
