"""
TaxArticle Model + CRUD Store
==============================

Pydantic model for Georgian Tax Code articles (309 articles).
MongoDB CRUD operations via TaxArticleStore (Fat Model pattern).

Pattern: @property lazy collection access (matches APIKeyStore).

Design decisions:
- last_amended_date: Optional[str] (ISO format) — BSON-safe
- ConfigDict(extra="ignore") — handles MongoDB _id field silently
- Embedding fields are Optional — populated by Task 4 pipeline
- Upsert filters None values to avoid overwriting existing embeddings
"""

import structlog
from enum import StrEnum
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.database import db_manager

logger = structlog.get_logger(__name__)


# =============================================================================
# ENUMS
# =============================================================================


class ArticleStatus(StrEnum):
    """Georgian Tax Code article lifecycle status."""
    ACTIVE = "active"
    REPEALED = "repealed"
    AMENDED = "amended"


# =============================================================================
# PYDANTIC MODEL
# =============================================================================


class TaxArticle(BaseModel):
    """
    Georgian Tax Code article (საქართველოს საგადასახადო კოდექსი).

    Fields follow the v5 implementation plan schema.
    Embedding fields are Optional — populated by the embedding pipeline (Task 4).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # --- Core fields ---
    article_number: int = Field(ge=1, le=500, description="Article number (1-309 typical)")
    kari: str = Field(min_length=1, description="კარი (Part)")
    tavi: str = Field(min_length=1, description="თავი (Chapter)")
    title: str = Field(min_length=1, description="Article title")
    body: str = Field(min_length=10, description="Full article text")

    # --- Semantic fields ---
    related_articles: List[int] = Field(default_factory=list, description="Cross-reference article numbers")
    is_exception: bool = Field(default=False, description="Lex specialis (exception) flag")
    last_amended_date: Optional[str] = Field(default=None, description="Last amendment date (ISO format string)")
    status: ArticleStatus = Field(default=ArticleStatus.ACTIVE, description="Article lifecycle status")

    # --- Embedding fields (populated by Task 4 pipeline) ---
    embedding: Optional[List[float]] = Field(default=None, description="768-dim vector embedding")
    embedding_model: Optional[str] = Field(default=None, description="Model that generated the embedding")
    embedding_text: Optional[str] = Field(default=None, description="Hierarchical text used for embedding")

    @field_validator("embedding")
    @classmethod
    def validate_embedding_dimensions(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Validate embedding is exactly 768 dimensions when present."""
        if v is not None and len(v) != 768:
            raise ValueError(f"Embedding must be 768 dimensions, got {len(v)}")
        return v


# =============================================================================
# CRUD STORE
# =============================================================================


class TaxArticleStore:
    """
    MongoDB CRUD for the tax_articles collection.

    Uses @property lazy pattern for collection access (matches APIKeyStore).
    """

    @property
    def _collection(self):
        """Get the tax_articles collection from the database manager."""
        return db_manager.db.tax_articles

    async def upsert(self, article: TaxArticle) -> str:
        """
        Insert or update a tax article by article_number.

        Filters None values from $set to avoid overwriting existing embeddings
        when re-scraping articles.

        Returns:
            "inserted" if new document, "updated" if existing.
        """
        doc = article.model_dump()
        # Filter None values to preserve existing fields (e.g., embeddings)
        doc = {k: v for k, v in doc.items() if v is not None}

        result = await self._collection.update_one(
            {"article_number": article.article_number},
            {"$set": doc},
            upsert=True,
        )

        action = "inserted" if result.upserted_id else "updated"
        logger.info(
            "tax_article_upserted",
            article_number=article.article_number,
            action=action,
        )
        return action

    async def update_embedding(
        self,
        article_number: int,
        embedding: List[float],
        embedding_model: str,
        embedding_text: str,
    ) -> bool:
        """
        Update only the embedding fields for a specific article.

        This is a targeted update — does not touch any other fields.

        Returns:
            True if the document was modified, False otherwise.
        """
        result = await self._collection.update_one(
            {"article_number": article_number},
            {"$set": {
                "embedding": embedding,
                "embedding_model": embedding_model,
                "embedding_text": embedding_text,
            }},
        )
        return result.modified_count > 0

    async def find_by_number(self, article_number: int) -> Optional[dict]:
        """
        Find a single article by its article_number.

        Returns:
            The article document (dict) or None if not found.
        """
        return await self._collection.find_one(
            {"article_number": article_number},
            {"_id": 0},
        )

    async def find_by_numbers(self, numbers: List[int]) -> List[dict]:
        """
        Find multiple articles by article_numbers using $in operator.

        Non-existent article numbers are silently ignored.

        Returns:
            List of article documents (dicts).
        """
        cursor = self._collection.find(
            {"article_number": {"$in": numbers}},
            {"_id": 0},
        )
        return await cursor.to_list(length=500)

    async def count(self) -> int:
        """Return the total number of articles in the collection."""
        return await self._collection.count_documents({})
