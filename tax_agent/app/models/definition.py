"""
Definition Model + CRUD Store
==============================

Pydantic model for Georgian Tax Code legal definitions (Article 8).
MongoDB CRUD operations via DefinitionStore (Fat Model pattern).

Pattern: @property lazy collection access (matches APIKeyStore, TaxArticleStore).

Design decisions:
- term_ka: matches existing DB index in database.py (not "term")
- ConfigDict(extra="ignore") — handles MongoDB _id field silently
- Embedding fields are Optional — populated by Task 4 pipeline
"""

import structlog
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.database import db_manager

logger = structlog.get_logger(__name__)


# =============================================================================
# PYDANTIC MODEL
# =============================================================================


class Definition(BaseModel):
    """
    Georgian Tax Code legal definition (მუხლი 8 — ტერმინთა განმარტებები).

    Each definition links a Georgian legal term to its official meaning
    and references the source article.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # --- Core fields ---
    term_ka: str = Field(min_length=1, description="Georgian term (unique key in DB)")
    definition: str = Field(min_length=5, description="Legal definition text")
    article_ref: int = Field(ge=1, description="Source article number (typically 8)")

    # --- Embedding fields (populated by Task 4 pipeline) ---
    embedding: Optional[List[float]] = Field(default=None, description="768-dim vector embedding")
    embedding_model: Optional[str] = Field(default=None, description="Model that generated the embedding")
    embedding_text: Optional[str] = Field(default=None, description="Text used for embedding (term + definition)")

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


class DefinitionStore:
    """
    MongoDB CRUD for the definitions collection.

    Uses @property lazy pattern for collection access (matches APIKeyStore).
    """

    @property
    def _collection(self):
        """Get the definitions collection from the database manager."""
        return db_manager.db.definitions

    async def upsert(self, defn: Definition) -> str:
        """
        Insert or update a definition by term_ka.

        Filters None values from $set to avoid overwriting existing embeddings.

        Returns:
            "inserted" if new document, "updated" if existing.
        """
        doc = defn.model_dump()
        doc = {k: v for k, v in doc.items() if v is not None}

        result = await self._collection.update_one(
            {"term_ka": defn.term_ka},
            {"$set": doc},
            upsert=True,
        )

        action = "inserted" if result.upserted_id else "updated"
        logger.info(
            "definition_upserted",
            term_ka=defn.term_ka,
            action=action,
        )
        return action

    async def update_embedding(
        self,
        term_ka: str,
        embedding: List[float],
        embedding_model: str,
        embedding_text: str,
    ) -> bool:
        """
        Update only the embedding fields for a specific definition.

        Returns:
            True if the document was modified, False otherwise.
        """
        result = await self._collection.update_one(
            {"term_ka": term_ka},
            {"$set": {
                "embedding": embedding,
                "embedding_model": embedding_model,
                "embedding_text": embedding_text,
            }},
        )
        return result.modified_count > 0

    async def find_by_term(self, term_ka: str) -> Optional[dict]:
        """
        Find a single definition by its Georgian term.

        Returns:
            The definition document (dict) or None if not found.
        """
        return await self._collection.find_one(
            {"term_ka": term_ka},
            {"_id": 0},
        )

    async def find_all(self) -> List[dict]:
        """
        Return all definitions in the collection.

        Returns:
            List of definition documents (dicts).
        """
        cursor = self._collection.find({}, {"_id": 0})
        return await cursor.to_list(length=1000)

    async def count(self) -> int:
        """Return the total number of definitions in the collection."""
        return await self._collection.count_documents({})
