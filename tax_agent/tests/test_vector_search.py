"""
Tests for Vector Search Pipeline — Task 5

16 tests covering: article number detection, semantic search, keyword search,
hybrid search (3-way merge), cross-reference enrichment, lex specialis
re-ranking, deduplication, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vector_search import (
    SearchError,
    _rrf_score,
    detect_article_number,
    enrich_with_cross_refs,
    hybrid_search,
    merge_and_rank,
    rerank_with_exceptions,
    search_by_keyword,
    search_by_semantic,
)


# ── T1–T3: Article Number Detection ──────────────────────────────────────────


def test_detect_article_number_georgian():
    """T1: Georgian pattern 'მუხლი 81' should return 81."""
    assert detect_article_number("მუხლი 81") == 81


def test_detect_article_number_english():
    """T2: English pattern 'article 81' should return 81."""
    assert detect_article_number("article 81") == 81
    assert detect_article_number("Article 42") == 42


def test_detect_article_number_missing():
    """T3: Query without article number should return None."""
    assert detect_article_number("საშემოსავლო გადასახადი") is None
    assert detect_article_number("income tax rate") is None


# ── T4–T5: Semantic Search ────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.embed_content", new_callable=AsyncMock)
@patch("app.services.vector_search.db_manager")
async def test_search_by_semantic_scored(mock_db_manager, mock_embed):
    """T4: Semantic search should return results with score field."""
    mock_embed.return_value = [0.1] * 768

    mock_results = [
        {
            "article_number": 81,
            "kari": "V",
            "tavi": "XIII",
            "title": "საშემოსავლო გადასახადი",
            "body": "ფიზიკური პირის მიერ...",
            "related_articles": [],
            "is_exception": False,
            "score": 0.85,
        },
        {
            "article_number": 82,
            "kari": "V",
            "tavi": "XIII",
            "title": "საგადასახადო შეღავათები",
            "body": "გათავისუფლებულია...",
            "related_articles": [81],
            "is_exception": True,
            "score": 0.72,
        },
    ]

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=mock_results)

    mock_collection = MagicMock()
    mock_collection.aggregate = MagicMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_db_manager.db = mock_db

    results = await search_by_semantic("income tax rate", threshold=0.7)

    assert len(results) == 2
    assert results[0]["score"] == 0.85
    assert results[1]["score"] == 0.72
    assert all("article_number" in r for r in results)

    # Verify pipeline was constructed correctly
    call_args = mock_collection.aggregate.call_args[0][0]
    assert call_args[0]["$vectorSearch"]["index"] == "tax_articles_vector_index"
    assert call_args[0]["$vectorSearch"]["filter"] == {"status": "active"}


@pytest.mark.asyncio
@patch("app.services.vector_search.embed_content", new_callable=AsyncMock)
@patch("app.services.vector_search.db_manager")
async def test_search_by_semantic_threshold(mock_db_manager, mock_embed):
    """T5: Results below threshold should be excluded."""
    mock_embed.return_value = [0.1] * 768

    mock_results = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "T", "body": "B", "related_articles": [], "is_exception": False},
        {"article_number": 99, "score": 0.40, "kari": "I", "tavi": "I",
         "title": "Low", "body": "Low", "related_articles": [], "is_exception": False},
    ]

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=mock_results)
    mock_collection = MagicMock()
    mock_collection.aggregate = MagicMock(return_value=mock_cursor)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_db_manager.db = mock_db

    results = await search_by_semantic("test", threshold=0.65)

    assert len(results) == 1
    assert results[0]["article_number"] == 81


# ── T6–T7: Hybrid Search ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
@patch("app.services.vector_search.TaxArticleStore")
async def test_hybrid_search_direct_lookup(mock_store_cls, mock_semantic, mock_keyword):
    """T6: Query with article number should trigger find_by_number + keyword."""
    mock_store = MagicMock()
    mock_store.find_by_number = AsyncMock(return_value={
        "article_number": 81,
        "kari": "V",
        "tavi": "XIII",
        "title": "საშემოსავლო გადასახადი",
        "body": "ფიზიკური პირის მიერ...",
        "related_articles": [],
        "is_exception": False,
    })
    mock_store_cls.return_value = mock_store

    mock_semantic.return_value = [
        {"article_number": 82, "score": 0.75, "kari": "V", "tavi": "XIII",
         "title": "T2", "body": "B2", "related_articles": [], "is_exception": False},
    ]
    mock_keyword.return_value = []  # No keyword results for this test

    results = await hybrid_search("მუხლი 81 საშემოსავლო")

    mock_store.find_by_number.assert_called_once_with(81)
    assert results[0]["article_number"] == 81
    assert results[0]["score"] == 1.0
    assert len(results) == 2


@pytest.mark.asyncio
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
async def test_hybrid_search_semantic_only(mock_semantic, mock_keyword):
    """T7: Query without article number should use semantic + keyword."""
    mock_semantic.return_value = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "T", "body": "B", "related_articles": [], "is_exception": False},
    ]
    mock_keyword.return_value = []  # No keyword results for this test

    results = await hybrid_search("income tax rate")

    mock_semantic.assert_called_once_with("income tax rate")
    mock_keyword.assert_called_once()  # Keyword search should also be called
    assert len(results) == 1
    assert results[0]["article_number"] == 81


# ── T8–T9: Cross-Reference Enrichment ────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.TaxArticleStore")
async def test_enrich_with_cross_refs(mock_store_cls):
    """T8: Related articles should be fetched and marked as cross-refs."""
    mock_store = MagicMock()
    mock_store.find_by_numbers = AsyncMock(return_value=[
        {"article_number": 82, "kari": "V", "tavi": "XIII",
         "title": "Exception", "body": "B", "related_articles": [], "is_exception": True},
    ])
    mock_store_cls.return_value = mock_store

    primary = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "General", "body": "B", "related_articles": [82], "is_exception": False},
    ]

    results = await enrich_with_cross_refs(primary)

    assert len(results) == 2
    assert results[1]["article_number"] == 82
    assert results[1]["is_cross_ref"] is True
    assert results[1]["score"] == 0.0
    mock_store.find_by_numbers.assert_called_once_with([82])


@pytest.mark.asyncio
@patch("app.services.vector_search.TaxArticleStore")
async def test_enrich_cross_refs_dedup(mock_store_cls):
    """T9: Cross-ref already in results should not be duplicated."""
    mock_store = MagicMock()
    mock_store.find_by_numbers = AsyncMock(return_value=[])
    mock_store_cls.return_value = mock_store

    primary = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "General", "body": "B", "related_articles": [81], "is_exception": False},
    ]

    results = await enrich_with_cross_refs(primary)

    assert len(results) == 1  # No new refs added
    mock_store.find_by_numbers.assert_not_called()  # Nothing to fetch


# ── T10: Lex Specialis Re-ranking ────────────────────────────────────────────


def test_rerank_with_exceptions():
    """T10: Exception should be placed immediately after its general rule."""
    results = [
        {"article_number": 81, "is_exception": False, "related_articles": [],
         "score": 0.9, "kari": "V", "tavi": "XIII", "title": "General",
         "body": "B"},
        {"article_number": 99, "is_exception": False, "related_articles": [],
         "score": 0.7, "kari": "I", "tavi": "I", "title": "Other",
         "body": "B"},
        {"article_number": 82, "is_exception": True, "related_articles": [81],
         "score": 0.6, "kari": "V", "tavi": "XIII", "title": "Exception",
         "body": "B"},
    ]

    reranked = rerank_with_exceptions(results)

    # General 81, then exception 82, then other 99
    assert reranked[0]["article_number"] == 81
    assert reranked[1]["article_number"] == 82
    assert reranked[2]["article_number"] == 99


# ── T11: Merge & Dedup ───────────────────────────────────────────────────────


def test_merge_and_rank_dedup():
    """T11: Duplicates should be removed via RRF, keeping highest-scored entry."""
    results = [
        {"article_number": 81, "score": 0.60, "search_type": "semantic"},
        {"article_number": 82, "score": 0.85, "search_type": "semantic"},
        {"article_number": 81, "score": 5.0, "search_type": "keyword"},  # Dup, keyword
    ]

    merged = merge_and_rank(results)

    assert len(merged) == 2
    # Article 81 appears in BOTH ranked lists → higher RRF score
    assert merged[0]["article_number"] == 81
    assert merged[0]["score"] == 5.0  # Keeps highest native score
    assert "rrf_score" in merged[0]
    assert merged[1]["article_number"] == 82


# ── T12: Embedding Failure ───────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.embed_content", new_callable=AsyncMock)
async def test_search_semantic_embed_failure(mock_embed):
    """T12: Embedding failure should raise SearchError."""
    mock_embed.side_effect = RuntimeError("API key expired")

    with pytest.raises(SearchError, match="Failed to embed query"):
        await search_by_semantic("test query")


# ── T13–T14: Keyword Search ──────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.db_manager")
async def test_search_by_keyword_returns_results(mock_db_manager):
    """T13: Keyword search should return results with score and search_type."""
    mock_results = [
        {
            "article_number": 81,
            "kari": "V",
            "tavi": "XIII",
            "title": "საშემოსავლო გადასახადი",
            "body": "ფიზიკური პირის მიერ...",
            "related_articles": [],
            "is_exception": False,
            "score": 5.2,
            "search_type": "keyword",
        },
    ]

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=mock_results)

    mock_collection = MagicMock()
    mock_collection.aggregate = MagicMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_db_manager.db = mock_db

    results = await search_by_keyword("საშემოსავლო გადასახადი")

    assert len(results) == 1
    assert results[0]["score"] == 5.2
    assert results[0]["search_type"] == "keyword"
    assert results[0]["article_number"] == 81

    # Verify pipeline used correct index and field paths
    call_args = mock_collection.aggregate.call_args[0][0]
    assert call_args[0]["$search"]["index"] == "tax_articles_keyword"
    assert call_args[0]["$search"]["text"]["path"] == ["body", "title"]


@pytest.mark.asyncio
@patch("app.services.vector_search.db_manager")
async def test_search_by_keyword_graceful_fallback(mock_db_manager):
    """T14: Keyword search should return [] on exception (graceful fallback)."""
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_collection.aggregate = MagicMock(side_effect=Exception("Index not found"))
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_db_manager.db = mock_db

    results = await search_by_keyword("test query")

    assert results == []


# ── T15–T16: Hybrid Search with Keyword Integration ─────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
async def test_hybrid_search_with_keyword_results(mock_semantic, mock_keyword):
    """T15: Hybrid search should merge semantic + keyword results."""
    mock_semantic.return_value = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "T1", "body": "B1", "related_articles": [], "is_exception": False},
    ]
    mock_keyword.return_value = [
        {"article_number": 82, "score": 4.5, "search_type": "keyword",
         "kari": "V", "tavi": "XIII", "title": "T2", "body": "B2",
         "related_articles": [], "is_exception": False},
    ]

    results = await hybrid_search("საშემოსავლო გადასახადი")

    # Both sources contribute results
    assert len(results) == 2
    article_numbers = {r["article_number"] for r in results}
    assert article_numbers == {81, 82}
    # RRF scores should be present
    assert all("rrf_score" in r for r in results)


@pytest.mark.asyncio
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
@patch("app.services.vector_search.TaxArticleStore")
async def test_hybrid_search_direct_plus_keyword(
    mock_store_cls, mock_semantic, mock_keyword
):
    """T16: Direct lookup + semantic + keyword should all merge correctly."""
    mock_store = MagicMock()
    mock_store.find_by_number = AsyncMock(return_value={
        "article_number": 81,
        "kari": "V",
        "tavi": "XIII",
        "title": "საშემოსავლო გადასახადი",
        "body": "ფიზიკური პირის მიერ...",
        "related_articles": [],
        "is_exception": False,
    })
    mock_store_cls.return_value = mock_store

    mock_semantic.return_value = [
        {"article_number": 82, "score": 0.75, "kari": "V", "tavi": "XIII",
         "title": "T2", "body": "B2", "related_articles": [], "is_exception": False},
    ]
    mock_keyword.return_value = [
        {"article_number": 83, "score": 3.1, "search_type": "keyword",
         "kari": "V", "tavi": "XIII", "title": "T3", "body": "B3",
         "related_articles": [], "is_exception": False},
    ]

    results = await hybrid_search("მუხლი 81 საშემოსავლო")

    # 3-way merge: direct(81) + semantic(82) + keyword(83)
    assert len(results) == 3
    article_numbers = {r["article_number"] for r in results}
    assert article_numbers == {81, 82, 83}
    # All results should have RRF scores
    assert all("rrf_score" in r for r in results)


# ── T17: Feature Flag Disabled ───────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.vector_search.settings")
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
async def test_hybrid_search_keyword_disabled(mock_semantic, mock_keyword, mock_settings):
    """T17: When keyword_search_enabled=False, keyword search must be skipped."""
    mock_settings.keyword_search_enabled = False

    mock_semantic.return_value = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "T", "body": "B", "related_articles": [], "is_exception": False},
    ]

    results = await hybrid_search("income tax rate")

    # Semantic should be called, keyword should NOT
    mock_semantic.assert_called_once()
    mock_keyword.assert_not_called()
    assert len(results) == 1
    assert results[0]["article_number"] == 81
