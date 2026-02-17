"""
Vector Search Pipeline — Task 5

Implements hybrid search (semantic + direct lookup), cross-reference
enrichment, lex specialis re-ranking, and deduplication for the
Georgian Tax Code RAG pipeline.
"""

import re
from typing import List, Optional

import structlog

from app.database import db_manager
from app.models.tax_article import TaxArticleStore
from app.services.embedding_service import embed_content
from config import settings

logger = structlog.get_logger(__name__)


# ── Custom Exception ──────────────────────────────────────────────────────────


class SearchError(Exception):
    """Raised when the search pipeline encounters an unrecoverable error."""

    pass


# ── Georgian Article Number Detection ─────────────────────────────────────────

ARTICLE_PATTERNS = [
    r"მუხლი\s*(\d+)",   # Georgian: "მუხლი 81"
    r"article\s*(\d+)",  # English:  "article 81"
    r"muxli\s*(\d+)",    # Transliterated: "muxli 81"
]


def detect_article_number(query: str) -> Optional[int]:
    """Extract an article number from a query string.

    Supports Georgian, English, and transliterated patterns.
    Returns the first match as an integer, or None if no match.
    """
    for pattern in ARTICLE_PATTERNS:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


# ── Semantic Search ───────────────────────────────────────────────────────────


async def search_by_semantic(
    query: str,
    limit: int | None = None,
    threshold: float | None = None,
) -> List[dict]:
    """Execute a $vectorSearch query against the tax_articles collection.

    Args:
        query: The search query text to embed and search.
        limit: Max results (defaults to settings.search_limit).
        threshold: Min similarity score (defaults to settings.similarity_threshold).

    Returns:
        List of article dicts with 'score' field, filtered by threshold.

    Raises:
        SearchError: If embedding fails or MongoDB aggregate errors.
    """
    effective_limit = limit or settings.search_limit
    effective_threshold = threshold or settings.similarity_threshold

    # ── Embed query ──
    try:
        query_vector = await embed_content(query)
    except Exception as e:
        logger.error("embedding_failed", query=query[:50], error=str(e))
        raise SearchError(f"Failed to embed query: {e}") from e

    # ── $vectorSearch pipeline ──
    pipeline = [
        {
            "$vectorSearch": {
                "index": "tax_articles_vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": effective_limit,
                "filter": {"status": "active"},
            }
        },
        {
            "$project": {
                "article_number": 1,
                "kari": 1,
                "tavi": 1,
                "title": 1,
                "body": 1,
                "related_articles": 1,
                "is_exception": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    try:
        db = db_manager.db
        collection = db["tax_articles"]
        cursor = collection.aggregate(pipeline)
        results = await cursor.to_list(length=effective_limit)
    except Exception as e:
        logger.error("vector_search_failed", query=query[:50], error=str(e))
        raise SearchError(f"Vector search failed: {e}") from e

    # ── Structured logging ──
    for r in results:
        logger.info(
            "search_result",
            query_preview=query[:50],
            article_number=r.get("article_number"),
            score=r.get("score"),
        )

    # ── Threshold filter ──
    return [r for r in results if r.get("score", 0) >= effective_threshold]


# ── Keyword Search ────────────────────────────────────────────────────────────


async def search_by_keyword(query: str, limit: int = 5) -> List[dict]:
    """Atlas Search keyword lookup using the text index.

    Graceful fallback: returns empty list if Atlas Search index
    doesn't exist or $search fails.

    Args:
        query: The search query text.
        limit: Max results (default 5).

    Returns:
        List of article dicts with 'score' and 'search_type' fields.
    """
    try:
        pipeline = [
            {
                "$search": {
                    "index": "tax_articles_keyword",
                    "text": {
                        "query": query,
                        "path": ["body", "title"],
                    },
                }
            },
            {"$limit": limit},
            {
                "$addFields": {
                    "score": {"$meta": "searchScore"},
                    "search_type": "keyword",
                }
            },
            {
                "$project": {
                    "article_number": 1,
                    "kari": 1,
                    "tavi": 1,
                    "title": 1,
                    "body": 1,
                    "related_articles": 1,
                    "is_exception": 1,
                    "score": 1,
                    "search_type": 1,
                }
            },
        ]

        db = db_manager.db
        collection = db["tax_articles"]
        cursor = collection.aggregate(pipeline)
        results = await cursor.to_list(length=limit)

        for r in results:
            logger.info(
                "keyword_result",
                query_preview=query[:50],
                article_number=r.get("article_number"),
                score=r.get("score"),
            )

        return results
    except Exception as e:
        logger.warning("keyword_search_failed", error=str(e))
        return []  # Graceful fallback


# ── Hybrid Search ─────────────────────────────────────────────────────────────


async def hybrid_search(query: str) -> List[dict]:
    """Execute a hybrid search: direct lookup + semantic + keyword.

    Three-way merge strategy:
    - Direct article lookup (score=1.0) if article number detected
    - Semantic search via vector embeddings
    - Keyword search via Atlas Search (gated by feature flag)

    Args:
        query: The user's search query.

    Returns:
        Merged, deduplicated, and ranked list of article dicts.
    """
    # ── Query validation (G5) ──
    if not query or not query.strip():
        return []

    article_num = detect_article_number(query)
    keyword_enabled = settings.keyword_search_enabled

    if article_num:
        store = TaxArticleStore()
        direct = await store.find_by_number(article_num)
        semantic = await search_by_semantic(query, limit=4)
        keyword = await search_by_keyword(query, limit=3) if keyword_enabled else []

        results = []
        if direct:
            direct_dict = direct if isinstance(direct, dict) else direct.model_dump()
            direct_dict["score"] = 1.0
            direct_dict["is_cross_ref"] = False
            results.append(direct_dict)
        results.extend(semantic)
        results.extend(keyword)
    else:
        semantic = await search_by_semantic(query)
        keyword = await search_by_keyword(query) if keyword_enabled else []
        results = semantic + keyword

    return merge_and_rank(results)


# ── Cross-Reference Enrichment ────────────────────────────────────────────────


async def enrich_with_cross_refs(
    results: List[dict],
    max_refs: int = 10,
) -> List[dict]:
    """Fetch related articles referenced by the search results.

    Adds cross-referenced articles that aren't already in the result set.
    Each cross-ref result is marked with is_cross_ref=True.

    Args:
        results: List of article dicts from search.
        max_refs: Maximum number of cross-references to fetch.

    Returns:
        Original results + cross-referenced articles (marked).
    """
    seen = {r["article_number"] for r in results}
    refs_to_fetch: List[int] = []

    for r in results:
        for ref in r.get("related_articles", []):
            if ref not in seen and len(refs_to_fetch) < max_refs:
                refs_to_fetch.append(ref)
                seen.add(ref)

    if not refs_to_fetch:
        return results

    store = TaxArticleStore()
    cross_refs = await store.find_by_numbers(refs_to_fetch)

    # ── Mark cross-refs (G4) ──
    enriched_refs = []
    for cr in cross_refs:
        cr_dict = cr if isinstance(cr, dict) else cr.model_dump()
        cr_dict["is_cross_ref"] = True
        cr_dict["score"] = 0.0
        enriched_refs.append(cr_dict)

    return results + enriched_refs


# ── Lex Specialis Re-ranking ─────────────────────────────────────────────────


def rerank_with_exceptions(results: List[dict]) -> List[dict]:
    """Re-rank results so exceptions follow their general rules.

    Uses the "general + attached exceptions" pattern: for each general
    rule, any exceptions referencing it are placed immediately after.
    Orphan exceptions (whose general rule isn't in results) are appended
    at the end.

    Args:
        results: List of article dicts to re-rank.

    Returns:
        Re-ranked list with exceptions attached to their general rules.
    """
    generals = [r for r in results if not r.get("is_exception")]
    exceptions = [r for r in results if r.get("is_exception")]
    attached: set[int] = set()
    reranked: List[dict] = []

    for g in generals:
        reranked.append(g)
        for i, e in enumerate(exceptions):
            if g["article_number"] in e.get("related_articles", []):
                reranked.append(e)
                attached.add(i)

    # ── Orphan exceptions (G7): general rule not in results ──
    for i, e in enumerate(exceptions):
        if i not in attached:
            reranked.append(e)

    return reranked


# ── Merge & Deduplicate ──────────────────────────────────────────────────────


def merge_and_rank(results: List[dict]) -> List[dict]:
    """Deduplicate results by article_number, keeping the highest score.

    Args:
        results: List of article dicts, possibly with duplicates.

    Returns:
        Deduplicated list sorted by score (descending).
    """
    seen: set[int] = set()
    unique: List[dict] = []

    for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
        article_num = r.get("article_number")
        if article_num is not None and article_num not in seen:
            seen.add(article_num)
            unique.append(r)

    return unique
