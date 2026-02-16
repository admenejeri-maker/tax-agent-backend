"""
Test CRUD — Mocked MongoDB Operations
=======================================

Tests TaxArticleStore and DefinitionStore CRUD methods using AsyncMock.
No real MongoDB connection required.

Patch targets:
- app.models.tax_article.db_manager (where TaxArticleStore imports it)
- app.models.definition.db_manager (where DefinitionStore imports it)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

from app.models.tax_article import TaxArticle, TaxArticleStore, ArticleStatus
from app.models.definition import Definition, DefinitionStore


# =============================================================================
# TEST HELPERS
# =============================================================================


def make_valid_article(**overrides) -> TaxArticle:
    """Factory for valid TaxArticle instances."""
    defaults = {
        "article_number": 81,
        "kari": "კარი II",
        "tavi": "თავი V",
        "title": "საშემოსავლო გადასახადის განაკვეთი",
        "body": "საშემოსავლო გადასახადის განაკვეთია 20 პროცენტი",
    }
    defaults.update(overrides)
    return TaxArticle(**defaults)


def make_valid_definition(**overrides) -> Definition:
    """Factory for valid Definition instances."""
    defaults = {
        "term_ka": "გადასახადი",
        "definition": "სავალდებულო, უპირობო ფულადი შენატანი ბიუჯეტში",
        "article_ref": 8,
    }
    defaults.update(overrides)
    return Definition(**defaults)


# =============================================================================
# TaxArticleStore — CRUD TESTS
# =============================================================================


class TestTaxArticleStoreCRUD:
    """Mocked CRUD tests for TaxArticleStore."""

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_upsert_inserts_new_article(self, mock_db):
        """Upsert a new article → update_one called with upsert=True."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.update_one.return_value = MagicMock(
            upserted_id="new_id_123"
        )

        store = TaxArticleStore()
        result = await store.upsert(make_valid_article())

        assert result == "inserted"
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"article_number": 81}
        assert call_args[1]["upsert"] is True

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_upsert_updates_existing_article(self, mock_db):
        """Upsert an existing article → returns 'updated'."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.update_one.return_value = MagicMock(upserted_id=None)

        store = TaxArticleStore()
        result = await store.upsert(make_valid_article())

        assert result == "updated"

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_upsert_filters_none_values(self, mock_db):
        """Upsert should not include None values in $set (protect embeddings)."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.update_one.return_value = MagicMock(upserted_id="id")

        store = TaxArticleStore()
        article = make_valid_article()  # embedding=None, embedding_model=None
        await store.upsert(article)

        call_args = mock_collection.update_one.call_args
        set_doc = call_args[0][1]["$set"]
        assert "embedding" not in set_doc
        assert "embedding_model" not in set_doc
        assert "embedding_text" not in set_doc
        assert "last_amended_date" not in set_doc

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_find_by_numbers_returns_matching(self, mock_db):
        """find_by_numbers with $in → returns only matching docs."""
        # Motor's .find() is synchronous (returns cursor), so use MagicMock
        mock_collection = MagicMock()
        mock_db.db.tax_articles = mock_collection

        # Mock cursor.to_list as async (cursor.to_list IS a coroutine)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"article_number": 81, "title": "Art 81"},
            {"article_number": 82, "title": "Art 82"},
        ])
        mock_collection.find.return_value = mock_cursor

        store = TaxArticleStore()
        results = await store.find_by_numbers([81, 82, 999])

        assert len(results) == 2
        mock_collection.find.assert_called_once()
        filter_arg = mock_collection.find.call_args[0][0]
        assert filter_arg == {"article_number": {"$in": [81, 82, 999]}}

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_update_embedding_targeted(self, mock_db):
        """update_embedding only sets embedding fields, nothing else."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.update_one.return_value = MagicMock(modified_count=1)

        store = TaxArticleStore()
        result = await store.update_embedding(
            article_number=81,
            embedding=[0.1] * 768,
            embedding_model="text-embedding-004",
            embedding_text="კარი II > თავი V > მუხლი 81: Test",
        )

        assert result is True
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"article_number": 81}
        set_doc = call_args[0][1]["$set"]
        assert "embedding" in set_doc
        assert "embedding_model" in set_doc
        assert "embedding_text" in set_doc
        assert len(set_doc) == 3  # Only embedding fields

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_find_by_number_returns_none(self, mock_db):
        """find_by_number for non-existent article → returns None."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.find_one.return_value = None

        store = TaxArticleStore()
        result = await store.find_by_number(999)

        assert result is None
        mock_collection.find_one.assert_called_once_with(
            {"article_number": 999},
            {"_id": 0},
        )

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_count(self, mock_db):
        """count returns total document count."""
        mock_collection = AsyncMock()
        mock_db.db.tax_articles = mock_collection
        mock_collection.count_documents.return_value = 309

        store = TaxArticleStore()
        result = await store.count()

        assert result == 309

    @pytest.mark.asyncio
    @patch("app.models.tax_article.db_manager")
    async def test_find_all(self, mock_db):
        """find_all returns all articles."""
        # Motor's .find() is synchronous (returns cursor), so use MagicMock
        mock_collection = MagicMock()
        mock_db.db.tax_articles = mock_collection

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"article_number": 81, "title": "Art 81"},
            {"article_number": 82, "title": "Art 82"},
        ])
        mock_collection.find.return_value = mock_cursor

        store = TaxArticleStore()
        results = await store.find_all()

        assert len(results) == 2
        mock_collection.find.assert_called_once_with({}, {"_id": 0})


# =============================================================================
# DefinitionStore — CRUD TESTS
# =============================================================================


class TestDefinitionStoreCRUD:
    """Mocked CRUD tests for DefinitionStore."""

    @pytest.mark.asyncio
    @patch("app.models.definition.db_manager")
    async def test_upsert_inserts_new_definition(self, mock_db):
        """Upsert a new definition → update_one called with term_ka filter."""
        mock_collection = AsyncMock()
        mock_db.db.definitions = mock_collection
        mock_collection.update_one.return_value = MagicMock(
            upserted_id="new_def_id"
        )

        store = DefinitionStore()
        result = await store.upsert(make_valid_definition())

        assert result == "inserted"
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"term_ka": "გადასახადი"}
        assert call_args[1]["upsert"] is True

    @pytest.mark.asyncio
    @patch("app.models.definition.db_manager")
    async def test_find_by_term(self, mock_db):
        """find_by_term returns matching definition."""
        mock_collection = AsyncMock()
        mock_db.db.definitions = mock_collection
        mock_collection.find_one.return_value = {
            "term_ka": "გადასახადი",
            "definition": "Test def",
            "article_ref": 8,
        }

        store = DefinitionStore()
        result = await store.find_by_term("გადასახადი")

        assert result is not None
        assert result["term_ka"] == "გადასახადი"
        mock_collection.find_one.assert_called_once_with(
            {"term_ka": "გადასახადი"},
            {"_id": 0},
        )

    @pytest.mark.asyncio
    @patch("app.models.definition.db_manager")
    async def test_find_all(self, mock_db):
        """find_all returns all definitions."""
        # Motor's .find() is synchronous (returns cursor), so use MagicMock
        mock_collection = MagicMock()
        mock_db.db.definitions = mock_collection

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"term_ka": "გადასახადი", "definition": "Def 1", "article_ref": 8},
            {"term_ka": "ბიუჯეტი", "definition": "Def 2", "article_ref": 8},
        ])
        mock_collection.find.return_value = mock_cursor

        store = DefinitionStore()
        results = await store.find_all()

        assert len(results) == 2

    @pytest.mark.asyncio
    @patch("app.models.definition.db_manager")
    async def test_update_embedding_targeted(self, mock_db):
        """update_embedding only sets embedding fields."""
        mock_collection = AsyncMock()
        mock_db.db.definitions = mock_collection
        mock_collection.update_one.return_value = MagicMock(modified_count=1)

        store = DefinitionStore()
        result = await store.update_embedding(
            term_ka="გადასახადი",
            embedding=[0.1] * 768,
            embedding_model="text-embedding-004",
            embedding_text="გადასახადი: სავალდებულო ფულადი შენატანი",
        )

        assert result is True
        call_args = mock_collection.update_one.call_args
        set_doc = call_args[0][1]["$set"]
        assert len(set_doc) == 3  # Only embedding fields
