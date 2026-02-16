"""
Test Embedding Service — Mocked API Tests
==========================================

Tests all 6 functions in embedding_service.py with mocked Google GenAI API.
No real API calls are made.

Patch targets:
- app.services.embedding_service._get_client (lazy singleton)
- app.services.embedding_service.asyncio.to_thread (async wrapper)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.embedding_service import (
    build_embedding_text,
    build_definition_text,
    embed_content,
    embed_batch,
    embed_and_store_all,
    reset_client,
    MAX_EMBEDDING_CHARS,
    EXPECTED_DIMENSIONS,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the client singleton before each test."""
    reset_client()
    yield
    reset_client()


def make_mock_embedding(dims: int = 768) -> MagicMock:
    """Create a mock embedding result with the given dimensions."""
    mock_emb = MagicMock()
    mock_emb.values = [0.1] * dims
    return mock_emb


def make_mock_result(count: int = 1, dims: int = 768) -> MagicMock:
    """Create a mock API result with `count` embeddings."""
    result = MagicMock()
    result.embeddings = [make_mock_embedding(dims) for _ in range(count)]
    return result


# =============================================================================
# TEXT BUILDERS
# =============================================================================


class TestBuildEmbeddingText:
    """Tests for build_embedding_text()."""

    def test_format_with_hierarchy(self):
        """Should produce Georgian hierarchy prefix format."""
        article = {
            "kari": "კარი IX",
            "tavi": "თავი I",
            "article_number": 169,
            "title": "სათამაშო ბიზნესის მოსაკრებელი",
            "body": "სათამაშო ბიზნესზე მოსაკრებელი 15 პროცენტია",
        }
        result = build_embedding_text(article)

        assert "კარი IX → თავი I → მუხლი 169." in result
        assert "სათამაშო ბიზნესის მოსაკრებელი" in result
        assert "სათამაშო ბიზნესზე მოსაკრებელი 15 პროცენტია" in result

    def test_handles_missing_fields(self):
        """Should not crash on partial article dict."""
        article = {"article_number": 1, "title": "Test"}
        result = build_embedding_text(article)
        assert "მუხლი 1" in result
        assert "Test" in result


class TestBuildDefinitionText:
    """Tests for build_definition_text()."""

    def test_format(self):
        """Should produce 'term: definition' format."""
        defn = {
            "term_ka": "გადასახადი",
            "definition": "სავალდებულო ფულადი შენატანი ბიუჯეტში",
        }
        result = build_definition_text(defn)
        assert result == "გადასახადი: სავალდებულო ფულადი შენატანი ბიუჯეტში"


# =============================================================================
# EMBED CONTENT
# =============================================================================


class TestEmbedContent:
    """Tests for embed_content() single embedding."""

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    async def test_returns_768_dims(self, mock_to_thread, mock_get_client):
        """embed_content should return exactly 768 floats."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_to_thread.return_value = make_mock_result(count=1, dims=768)

        result = await embed_content("test text", model="text-embedding-004")

        assert len(result) == 768
        assert all(isinstance(v, float) for v in result)
        mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    async def test_dimension_mismatch_raises(self, mock_to_thread, mock_get_client):
        """embed_content should raise ValueError if dims != 768."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_to_thread.return_value = make_mock_result(count=1, dims=512)

        with pytest.raises(ValueError, match="Expected 768 dimensions"):
            await embed_content("test text", model="text-embedding-004")


# =============================================================================
# EMBED BATCH
# =============================================================================


class TestEmbedBatch:
    """Tests for embed_batch() with chunking."""

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.embedding_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_chunking(self, mock_sleep, mock_to_thread, mock_get_client):
        """250 texts → 3 batches of (100, 100, 50)."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Each call returns embeddings matching the chunk size
        mock_to_thread.side_effect = [
            make_mock_result(count=100),  # Batch 1: 100
            make_mock_result(count=100),  # Batch 2: 100
            make_mock_result(count=50),   # Batch 3: 50
        ]

        texts = [f"text_{i}" for i in range(250)]
        result = await embed_batch(texts, batch_size=100, model="text-embedding-004")

        assert len(result) == 250
        assert mock_to_thread.call_count == 3
        # Should sleep between batches (2 times for 3 batches)
        assert mock_sleep.call_count == 2


# =============================================================================
# TRUNCATION
# =============================================================================


class TestTruncation:
    """Tests for text truncation warning."""

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.services.embedding_service.logger")
    async def test_truncation_warning(self, mock_logger, mock_to_thread, mock_get_client):
        """Text > MAX_EMBEDDING_CHARS should be truncated + warning logged."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_to_thread.return_value = make_mock_result(count=1, dims=768)

        long_text = "x" * (MAX_EMBEDDING_CHARS + 1000)
        await embed_content(long_text, model="text-embedding-004")

        # Verify truncation warning was logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "text_truncated"

        # Verify the text passed to API was truncated
        api_call_args = mock_to_thread.call_args
        actual_text = api_call_args[1].get("contents") or api_call_args[0][2]
        assert len(actual_text) == MAX_EMBEDDING_CHARS


# =============================================================================
# ORCHESTRATOR
# =============================================================================


class TestEmbedAndStoreAll:
    """Tests for embed_and_store_all() orchestrator."""

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    async def test_embeds_all_articles(self, mock_to_thread, mock_get_client):
        """Orchestrator calls update_embedding for each article."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_to_thread.return_value = make_mock_result(count=1, dims=768)

        # Mock stores
        article_store = AsyncMock()
        article_store.find_all.return_value = [
            {"article_number": 81, "kari": "კარი II", "tavi": "თავი V",
             "title": "Test Art", "body": "Body text"},
            {"article_number": 82, "kari": "კარი II", "tavi": "თავი V",
             "title": "Test Art 2", "body": "Body text 2"},
        ]

        definition_store = AsyncMock()
        definition_store.find_all.return_value = []

        stats = await embed_and_store_all(article_store, definition_store)

        assert stats["articles_embedded"] == 2
        assert stats["definitions_embedded"] == 0
        assert stats["errors"] == 0
        assert article_store.update_embedding.call_count == 2

    @pytest.mark.asyncio
    @patch("app.services.embedding_service._get_client")
    @patch("app.services.embedding_service.asyncio.to_thread", new_callable=AsyncMock)
    async def test_error_isolation(self, mock_to_thread, mock_get_client):
        """One API failure should not kill the pipeline."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # First call succeeds, second fails, third succeeds
        mock_to_thread.side_effect = [
            make_mock_result(count=1, dims=768),  # Article 81 OK
            Exception("API quota exceeded"),       # Article 82 FAIL
            make_mock_result(count=1, dims=768),  # Definition OK
        ]

        article_store = AsyncMock()
        article_store.find_all.return_value = [
            {"article_number": 81, "kari": "კარი II", "tavi": "თავი V",
             "title": "Art 81", "body": "Body"},
            {"article_number": 82, "kari": "კარი II", "tavi": "თავი V",
             "title": "Art 82", "body": "Body"},
        ]

        definition_store = AsyncMock()
        definition_store.find_all.return_value = [
            {"term_ka": "გადასახადი", "definition": "Tax"},
        ]

        stats = await embed_and_store_all(article_store, definition_store)

        assert stats["articles_embedded"] == 1   # Only 81 succeeded
        assert stats["definitions_embedded"] == 1
        assert stats["errors"] == 1              # Article 82 failed
