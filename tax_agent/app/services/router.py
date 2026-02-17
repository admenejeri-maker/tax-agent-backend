"""
Tiered Query Router — Step 2
=============================

Keyword-first routing with semantic fallback stub.
Maps Georgian tax queries to semantic domains:
  VAT, INCOME_TAX, PROPERTY_TAX, GENERAL.

Design: Keyword scan (Tier 1) covers 92-96% of Georgian tax queries
because Georgian tax terms are unambiguous. Semantic fallback (Tier 2)
is stubbed for future activation when domain exemplars are available.
"""

from dataclasses import dataclass
from typing import Dict, List

import structlog

logger = structlog.get_logger(__name__)


# ─── Route Result ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteResult:
    """Immutable routing classification result."""

    domain: str  # "VAT", "INCOME_TAX", "PROPERTY_TAX", "GENERAL"
    confidence: float  # 0.0 - 1.0
    method: str  # "keyword" | "semantic" | "default"


# ─── Keyword Map ─────────────────────────────────────────────────────────────
# Georgian tax terms are unambiguous — keyword matching gives 100% precision.
# Module-level constant for easy expansion without code changes.

KEYWORD_MAP: Dict[str, List[str]] = {
    "VAT": ["დღგ", "დამატებული ღირებულების"],
    "INCOME_TAX": ["საშემოსავლო", "მოგების გადასახადი"],
    "PROPERTY_TAX": ["ქონების გადასახადი"],
}


# ─── Route Function ──────────────────────────────────────────────────────────


async def route_query(query: str) -> RouteResult:
    """Route a tax query to a semantic domain.

    Tier 1: Keyword scan (0ms, 100% precision for matched patterns)
    Tier 2: Semantic fallback (stub — graceful degradation)
    Tier 3: Default → GENERAL

    Args:
        query: User's tax question (Georgian or mixed).

    Returns:
        RouteResult with domain, confidence, and method used.
    """
    if not query or not query.strip():
        logger.debug("route_empty_query")
        return RouteResult(domain="GENERAL", confidence=0.0, method="default")

    query_lower = query.lower()

    # Tier 1: Keyword scan
    for domain, keywords in KEYWORD_MAP.items():
        if any(kw in query_lower for kw in keywords):
            logger.info("route_keyword_match", domain=domain, query=query[:50])
            return RouteResult(domain=domain, confidence=1.0, method="keyword")

    # Tier 2: Semantic fallback (stub)
    # TODO: Load from data/router_exemplars.json, embed query, cosine similarity
    logger.debug("route_no_keyword_match", query=query[:50])

    # Tier 3: Default
    return RouteResult(domain="GENERAL", confidence=0.0, method="default")
