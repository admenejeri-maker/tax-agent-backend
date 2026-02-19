"""
Vector Search Pipeline — Task 5

Implements hybrid search (semantic + direct lookup + keyword),
cross-reference enrichment, lex specialis re-ranking, and
Reciprocal Rank Fusion (RRF) deduplication for the Georgian
Tax Code RAG pipeline.
"""

import asyncio
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
    r"მუხლი\s*([0-9]+)",   # Georgian: "მუხლი 81"
    r"article\s*([0-9]+)",  # English:  "article 81"
    r"muxli\s*([0-9]+)",    # Transliterated: "muxli 81"
]

# BSON int64 max — prevents MongoDB overflow on absurd article numbers
_MAX_ARTICLE_NUMBER = 2**63 - 1


def detect_article_number(query: str) -> Optional[int]:
    """Extract an article number from a query string.

    Supports Georgian, English, and transliterated patterns.
    Returns the first match as an integer, or None if no match.
    Clamps to BSON int64 range to prevent MongoDB overflow.
    """
    if not isinstance(query, str):
        return None
    for pattern in ARTICLE_PATTERNS:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            if num > _MAX_ARTICLE_NUMBER:
                logger.warning("article_number_overflow", raw=match.group(1))
                return None
            return num
    return None


# ── Search Filter Builder ─────────────────────────────────────────────────────


def _build_search_filter(domain: Optional[str] = None) -> dict:
    """Build $vectorSearch pre-filter.

    Args:
        domain: Tax domain from router. If set and not GENERAL,
                adds domain constraint to filter.

    Returns:
        Filter dict for $vectorSearch 'filter' parameter.
    """
    base = {"status": "active"}
    if domain and domain != "GENERAL":
        base["domain"] = {"$in": [domain, "GENERAL"]}
    return base


# ── Semantic Search ───────────────────────────────────────────────────────────


async def _do_semantic_search(
    query: str,
    limit: int,
    threshold: float,
    domain: Optional[str] = None,
) -> List[dict]:
    """Internal: execute a single $vectorSearch query.

    Args:
        query: The search query text to embed and search.
        limit: Max results.
        threshold: Min similarity score.
        domain: Optional domain for pre-filtering.

    Returns:
        List of article dicts with 'score' field, filtered by threshold.

    Raises:
        SearchError: If embedding fails or MongoDB aggregate errors.
    """
    # ── Embed query ──
    try:
        query_vector = await embed_content(query)
    except Exception as e:
        logger.error("embedding_failed", query=query[:50], error=str(e))
        raise SearchError(f"Failed to embed query: {e}") from e

    search_filter = _build_search_filter(domain)

    # ── $vectorSearch pipeline ──
    pipeline = [
        {
            "$vectorSearch": {
                "index": "tax_articles_vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": limit,
                "filter": search_filter,
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
        results = await cursor.to_list(length=limit)
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
    return [r for r in results if r.get("score", 0) >= threshold]


async def search_by_semantic(
    query: str,
    limit: int | None = None,
    threshold: float | None = None,
    domain: Optional[str] = None,
) -> List[dict]:
    """Execute a $vectorSearch query with optional domain filter + fallback.

    Args:
        query: The search query text to embed and search.
        limit: Max results (defaults to settings.search_limit).
        threshold: Min similarity score (defaults to settings.similarity_threshold).
        domain: Optional tax domain for pre-filtering.

    Returns:
        List of article dicts with 'score' field, filtered by threshold.

    Raises:
        SearchError: If embedding fails or MongoDB aggregate errors.
    """
    effective_limit = limit or settings.search_limit
    effective_threshold = threshold or settings.similarity_threshold

    results = await _do_semantic_search(
        query, effective_limit, effective_threshold, domain=domain,
    )

    # ── Fallback: if domain filter gives < 2 results, retry without filter ──
    if domain and domain != "GENERAL" and len(results) < 2:
        logger.warning(
            "domain_filter_fallback",
            domain=domain,
            results_with_filter=len(results),
        )
        results = await _do_semantic_search(
            query, effective_limit, effective_threshold, domain=None,
        )

    return results


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
    if not query or not query.strip():
        return []

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



# ── Helpers ───────────────────────────────────────────────────────────────────


async def _noop() -> list:
    """No-op coroutine returning [] — used when keyword search is disabled."""
    return []


# ── Hybrid Search ─────────────────────────────────────────────────────────────


async def hybrid_search(
    query: str,
    domain: Optional[str] = None,
) -> List[dict]:
    """Execute a hybrid search: direct lookup + semantic + keyword.

    Three-way merge strategy:
    - Direct article lookup (score=1.0) if article number detected
    - Semantic search via vector embeddings (domain-filtered)
    - Keyword search via Atlas Search (gated by feature flag)

    Args:
        query: The user's search query.
        domain: Optional tax domain for semantic search pre-filtering.

    Returns:
        Merged, deduplicated, and ranked list of article dicts.
    """
    # ── Query validation (G5) ──
    if not isinstance(query, str) or not query.strip():
        return []

    article_num = detect_article_number(query)
    keyword_enabled = settings.keyword_search_enabled

    if article_num is not None:
        store = TaxArticleStore()
        # Run all three searches concurrently (F3)
        direct_coro = store.find_by_number(article_num)
        semantic_coro = search_by_semantic(query, limit=4, domain=domain)
        keyword_coro = search_by_keyword(query, limit=3) if keyword_enabled else _noop()

        gather_results = await asyncio.gather(
            direct_coro, semantic_coro, keyword_coro,
            return_exceptions=True,
        )
        direct = gather_results[0] if not isinstance(gather_results[0], BaseException) else None
        semantic = gather_results[1] if not isinstance(gather_results[1], BaseException) else []
        keyword_raw = gather_results[2] if not isinstance(gather_results[2], BaseException) else []
        keyword = keyword_raw if isinstance(keyword_raw, list) else []

        # Log any partial failures
        for i, label in enumerate(["direct", "semantic", "keyword"]):
            if isinstance(gather_results[i], BaseException):
                logger.error("partial_search_failure", source=label, error=str(gather_results[i]))

        results = []
        if direct:
            direct_dict = direct if isinstance(direct, dict) else direct.model_dump()
            direct_dict["score"] = 1.0
            direct_dict["search_type"] = "direct"
            direct_dict["is_cross_ref"] = False
            results.append(direct_dict)
        results.extend(semantic)
        results.extend(keyword)
    else:
        # Run semantic + keyword concurrently (F3)
        semantic_coro = search_by_semantic(query, domain=domain)
        keyword_coro = search_by_keyword(query) if keyword_enabled else _noop()

        gather_results = await asyncio.gather(
            semantic_coro, keyword_coro,
            return_exceptions=True,
        )
        semantic = gather_results[0] if not isinstance(gather_results[0], BaseException) else []
        keyword_raw = gather_results[1] if not isinstance(gather_results[1], BaseException) else []

        # Log any partial failures
        for i, label in enumerate(["semantic", "keyword"]):
            if isinstance(gather_results[i], BaseException):
                logger.error("partial_search_failure", source=label, error=str(gather_results[i]))

        keyword = keyword_raw if isinstance(keyword_raw, list) else []
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
        cr_dict["search_type"] = "cross_ref"
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


# ── Merge & Deduplicate (RRF — F1 Fix) ──────────────────────────────────────

RRF_K = 60  # Standard RRF constant (Cormack et al. 2009)


def _rrf_score(ranked_lists: List[List[dict]]) -> List[dict]:
    """Compute Reciprocal Rank Fusion scores across ranked lists.

    RRF is scale-agnostic: it converts raw scores (which may be on
    different scales like BM25 vs cosine similarity) into rank-based
    fusion scores.  Formula: RRF(d) = Σ 1 / (K + rank_i(d))

    Args:
        ranked_lists: List of result lists, each pre-sorted by their
                      native score descending.

    Returns:
        List of dicts with 'rrf_score' added, sorted by RRF score descending.
    """
    scores: dict[int, float] = {}  # article_number → cumulative RRF score
    registry: dict[int, dict] = {}  # article_number → best dict entry

    for rlist in ranked_lists:
        for rank, r in enumerate(rlist, start=1):
            article_num = r.get("article_number")
            if article_num is None:
                continue
            rrf = 1.0 / (RRF_K + rank)
            scores[article_num] = scores.get(article_num, 0.0) + rrf
            # Keep the entry with the highest native score
            if article_num not in registry or r.get("score", 0) > registry[article_num].get("score", 0):
                registry[article_num] = r

    # Build output sorted by RRF score
    fused = []
    for article_num in sorted(scores, key=scores.get, reverse=True):
        entry = dict(registry[article_num])
        entry["rrf_score"] = round(scores[article_num], 6)
        fused.append(entry)

    return fused


def merge_and_rank(results: List[dict]) -> List[dict]:
    """Deduplicate results using Reciprocal Rank Fusion (RRF).

    Splits results by search_type, ranks each source independently,
    then fuses using RRF to produce a scale-agnostic merged ranking.

    Args:
        results: List of article dicts, possibly with duplicates.

    Returns:
        Deduplicated list sorted by RRF score (descending).
    """
    if not results:
        return []

    # ── Split by source for independent ranking ──
    buckets: dict[str, List[dict]] = {}
    for r in results:
        source = r.get("search_type", "semantic")
        buckets.setdefault(source, []).append(r)

    # Sort each bucket by its native score (descending)
    ranked_lists = [
        sorted(bucket, key=lambda x: x.get("score", 0), reverse=True)
        for bucket in buckets.values()
    ]

    return _rrf_score(ranked_lists)
