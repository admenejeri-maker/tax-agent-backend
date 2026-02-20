"""
Tests for Vector Search Pipeline — Task 5

17+ tests covering: article number detection, semantic search, keyword search,
hybrid search (3-way merge), cross-reference enrichment, lex specialis
re-ranking, deduplication, error handling, and adversarial inputs.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vector_search import (
    SearchError,
    _MAX_ARTICLE_NUMBER,
    _build_search_filter,
    _noop,
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

    mock_semantic.assert_called_once_with("income tax rate", domain=None)
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


@pytest.mark.asyncio
@patch("app.services.vector_search.TaxArticleStore")
async def test_enriched_results_have_search_type(mock_store_cls):
    """Phase 2 S2 fix: enriched cross-refs include search_type='cross_ref'."""
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

    assert results[1]["search_type"] == "cross_ref"
    assert results[1]["is_cross_ref"] is True


@pytest.mark.asyncio
@patch("app.services.vector_search.TaxArticleStore")
async def test_enrich_max_refs_cap(mock_store_cls):
    """Phase 2: max_refs=2 caps enrichment even when more refs available."""
    mock_store = MagicMock()
    mock_store.find_by_numbers = AsyncMock(return_value=[
        {"article_number": 82, "kari": "V", "tavi": "XIII",
         "title": "T82", "body": "B", "related_articles": [], "is_exception": False},
        {"article_number": 83, "kari": "V", "tavi": "XIII",
         "title": "T83", "body": "B", "related_articles": [], "is_exception": False},
    ])
    mock_store_cls.return_value = mock_store

    primary = [
        {"article_number": 81, "score": 0.85, "kari": "V", "tavi": "XIII",
         "title": "General", "body": "B", "related_articles": [82, 83, 84, 85],
         "is_exception": False},
    ]

    results = await enrich_with_cross_refs(primary, max_refs=2)

    # Primary + max 2 cross-refs
    cross_refs = [r for r in results if r.get("is_cross_ref")]
    assert len(cross_refs) <= 2


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


# ── T18–T23: Adversarial Input Tests ─────────────────────────────────────────


def test_detect_article_non_string_input():
    """T18: Non-string input must return None, not crash."""
    assert detect_article_number(123) is None
    assert detect_article_number(None) is None
    assert detect_article_number(["article 1"]) is None


def test_detect_article_bson_overflow():
    """T19: Article number exceeding BSON int64 max must return None."""
    huge = str(_MAX_ARTICLE_NUMBER + 1)
    assert detect_article_number(f"article {huge}") is None
    # Valid large number just under limit should still work
    assert detect_article_number("article 999999") == 999999


def test_detect_article_arabic_numerals_rejected():
    """T20: Arabic-Indic numerals (١٨٠) must NOT match — ASCII only."""
    assert detect_article_number("article ١٨٠") is None
    assert detect_article_number("მუხლი ٨١") is None
    # But standard digits still work
    assert detect_article_number("article 180") == 180


def test_detect_article_zero():
    """T21: Article 0 must be detected (not skipped by truthiness)."""
    result = detect_article_number("article 0")
    assert result == 0


@pytest.mark.asyncio
@patch("app.services.vector_search.settings")
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
async def test_hybrid_partial_failure_resilience(mock_semantic, mock_keyword, mock_settings):
    """T22: If semantic search fails, keyword results still returned."""
    mock_settings.keyword_search_enabled = True
    mock_semantic.side_effect = SearchError("embedding API down")
    mock_keyword.return_value = [
        {"article_number": 81, "score": 3.5, "search_type": "keyword",
         "kari": "V", "tavi": "XIII", "title": "T", "body": "B",
         "related_articles": [], "is_exception": False},
    ]

    results = await hybrid_search("income tax")

    # Should NOT crash — keyword results survive
    assert len(results) == 1
    assert results[0]["article_number"] == 81


@pytest.mark.asyncio
@patch("app.services.vector_search.settings")
@patch("app.services.vector_search.search_by_keyword", new_callable=AsyncMock)
@patch("app.services.vector_search.search_by_semantic", new_callable=AsyncMock)
@patch("app.services.vector_search.TaxArticleStore")
async def test_hybrid_direct_tagged_as_direct(mock_store_cls, mock_semantic, mock_keyword, mock_settings):
    """T23: Direct lookup results must have search_type='direct'."""
    mock_settings.keyword_search_enabled = False

    mock_store = MagicMock()
    mock_store.find_by_number = AsyncMock(return_value={
        "article_number": 81, "kari": "V", "tavi": "XIII",
        "title": "T", "body": "B", "related_articles": [], "is_exception": False,
    })
    mock_store_cls.return_value = mock_store

    mock_semantic.return_value = []

    results = await hybrid_search("მუხლი 81")

    assert len(results) == 1
    assert results[0]["search_type"] == "direct"
    assert results[0]["score"] == 1.0


# ── Domain Filter & Fallback Tests ────────────────────────────────────────────


def test_build_search_filter_no_domain():
    """_build_search_filter with no domain returns only status:active."""
    result = _build_search_filter()
    assert result == {"status": "active"}


def test_build_search_filter_general_domain():
    """_build_search_filter with GENERAL domain returns only status:active."""
    result = _build_search_filter(domain="GENERAL")
    assert result == {"status": "active"}


def test_build_search_filter_specific_domain():
    """_build_search_filter with specific domain includes $in filter."""
    result = _build_search_filter(domain="VAT")
    assert result == {"status": "active", "domain": {"$in": ["VAT", "GENERAL"]}}


@pytest.mark.asyncio
@patch("app.services.vector_search._do_semantic_search", new_callable=AsyncMock)
async def test_semantic_search_domain_fallback(mock_do_search):
    """search_by_semantic retries without domain when filtered results < 2.

    First call (with domain) returns 1 result → triggers fallback.
    Second call (without domain) returns 3 results.
    """
    # 1 result with domain filter → triggers fallback
    mock_do_search.side_effect = [
        [{"article_number": 99, "score": 0.85}],         # domain-filtered: 1 result
        [
            {"article_number": 99, "score": 0.85},
            {"article_number": 100, "score": 0.80},
            {"article_number": 101, "score": 0.75},
        ],  # unfiltered: 3 results
    ]

    results = await search_by_semantic("test query", domain="CORPORATE_TAX")

    # Should have fallen back and returned 3 results
    assert len(results) == 3
    assert mock_do_search.call_count == 2
    # First call: with domain
    assert mock_do_search.call_args_list[0].kwargs["domain"] == "CORPORATE_TAX"
    # Second call: without domain
    assert mock_do_search.call_args_list[1].kwargs["domain"] is None


# ── Fix 1 — RRF Collision Guard (TDD) ────────────────────────────────────────


def test_cross_refs_never_outrank_primary_rrf_collision():
    """Fix 1 — T24: Singleton cross-ref must NOT outrank singleton primary via RRF tie.

    Before fix: cross_ref forms its own RRF bucket (rank=1), same RRF score as a lonely
    primary result → undefined sort order. After fix: primary always comes first.
    """
    results = [
        {"article_number": 81, "score": 0.85, "search_type": "semantic"},
        {"article_number": 99, "score": 0.0,  "search_type": "cross_ref"},
    ]
    merged = merge_and_rank(results)
    assert merged[0]["article_number"] == 81, "Primary must always rank before cross-ref"
    assert merged[1]["article_number"] == 99
    assert merged[1]["search_type"] == "cross_ref"


def test_cross_refs_appended_after_all_primary_results():
    """Fix 1 — T25: ALL cross-refs must land after ALL primary results, regardless of count."""
    results = [
        {"article_number": 10, "score": 0.9, "search_type": "semantic"},
        {"article_number": 20, "score": 0.6, "search_type": "keyword"},
        {"article_number": 30, "score": 0.4, "search_type": "semantic"},
        {"article_number": 99, "score": 0.0, "search_type": "cross_ref"},
        {"article_number": 100, "score": 0.0, "search_type": "cross_ref"},
    ]
    merged = merge_and_rank(results)
    last_primary_idx = max(
        i for i, r in enumerate(merged) if r.get("search_type") != "cross_ref"
    )
    first_cross_idx = min(
        i for i, r in enumerate(merged) if r.get("search_type") == "cross_ref"
    )
    assert last_primary_idx < first_cross_idx, (
        f"Primary at idx {last_primary_idx} must precede first cross-ref at idx {first_cross_idx}"
    )


def test_merge_and_rank_no_cross_refs_unchanged():
    """Fix 1 — T26: Normal operation (no cross-refs) must be unaffected by the fix."""
    results = [
        {"article_number": 10, "score": 0.9, "search_type": "semantic"},
        {"article_number": 20, "score": 0.3, "search_type": "keyword"},
    ]
    merged = merge_and_rank(results)
    assert len(merged) == 2
    article_numbers = {r["article_number"] for r in merged}
    assert article_numbers == {10, 20}


def test_merge_and_rank_cross_ref_same_article_number_as_primary():
    """Fix 1 — T27: Cross-ref sharing article_number with a primary appears once in primary list,
    and once in the cross-ref tail — dedup is handled upstream by enrich_with_cross_refs.
    This test verifies the separation logic doesn't lose the primary entry.
    """
    results = [
        {"article_number": 81, "score": 0.85, "search_type": "semantic"},
        {"article_number": 81, "score": 0.0,  "search_type": "cross_ref"},
    ]
    merged = merge_and_rank(results)
    primary = [r for r in merged if r.get("search_type") != "cross_ref"]
    cross = [r for r in merged if r.get("search_type") == "cross_ref"]
    assert len(primary) == 1
    assert primary[0]["article_number"] == 81
    assert len(cross) == 1
    assert cross[0]["article_number"] == 81
