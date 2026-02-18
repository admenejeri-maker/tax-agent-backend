"""
RAG Response Model — Task 6c
==============================

Standardized response structure for the RAG pipeline.
All code paths return a RAGResponse — never an unstructured dict.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SourceMetadata(BaseModel):
    """Metadata for a single source used in the response."""

    article_number: Optional[str] = None
    chapter: Optional[str] = None
    title: Optional[str] = None
    score: float = 0.0
    url: Optional[str] = None  # Matsne deep-link
    text: Optional[str] = None  # Source chunk body (truncated to 2000 chars)

    @field_validator("article_number", mode="before")
    @classmethod
    def coerce_article_number(cls, v):
        """MongoDB stores article_number as int; coerce to str."""
        if v is None:
            return v
        return str(v)


class RAGResponse(BaseModel):
    """Structured response from the RAG pipeline.

    Every pipeline exit point returns this model, including error cases.
    """

    answer: str = ""
    sources: List[str] = Field(default_factory=list)
    source_metadata: List[SourceMetadata] = Field(default_factory=list)
    confidence_score: float = 0.0
    disclaimer: Optional[str] = None
    temporal_warning: Optional[str] = None
    error: Optional[str] = None
    safety_fallback: bool = False  # True if response used relaxed safety / backup model
