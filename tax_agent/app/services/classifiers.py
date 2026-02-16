"""
Pre-Retrieval Classifiers — Task 6a
=====================================

Three classifiers that run BEFORE vector search to enrich query context:
1. Red Zone Classifier — detect calculation/amount requests
2. Term Resolver — match query terms against tax definitions DB
3. Past-Date Detector — detect historical year references

All classifiers are standalone and independently testable.
"""

import re
from typing import List, Optional

import structlog

from app.models.definition import DefinitionStore

logger = structlog.get_logger(__name__)

# ─── Red Zone Patterns ──────────────────────────────────────────────────────
# Detects queries requesting specific calculations or amounts.
# These require a disclaimer: "consult a professional for exact amounts."

RED_ZONE_PATTERNS = [
    r"რამდენი",
    r"გამოთვალე",
    r"რა გადასახადი",
    r"რამდენია",
]


def classify_red_zone(query: str) -> bool:
    """Detect if query requests a specific calculation or amount.

    Args:
        query: User's tax question in Georgian.

    Returns:
        True if a Red Zone pattern matches (disclaimer needed).
    """
    return any(re.search(p, query, re.IGNORECASE) for p in RED_ZONE_PATTERNS)


# ─── Term Resolver ───────────────────────────────────────────────────────────
# Matches query text against all known tax definitions (substring match).
# Async because DefinitionStore.find_all() is an async DB call.


async def resolve_terms(query: str) -> List[dict]:
    """Match query against known Georgian tax definitions.

    Loads all definitions from DB, then filters by substring match.
    Returns matched definitions for injection into prompt context.

    Args:
        query: User's tax question in Georgian.

    Returns:
        List of matching definition dicts. Empty list on failure (graceful degradation).
    """
    try:
        store = DefinitionStore()
        all_defs = await store.find_all()
        matched = [
            d for d in all_defs
            if d.get("term_ka") and d["term_ka"] in query
        ]
        logger.info(
            "terms_resolved",
            query=query[:50],
            matched_count=len(matched),
        )
        return matched
    except Exception as e:
        logger.warning("term_resolution_failed", error=str(e))
        return []


# ─── Past-Date Detector ─────────────────────────────────────────────────────
# Detects year references like "2022 წელს" to add temporal warnings.

PAST_DATE_PATTERN = re.compile(r"(20\d{2})\s*წელ")


def detect_past_date(query: str) -> tuple[bool, Optional[int]]:
    """Detect past-year references in a tax query.

    Args:
        query: User's tax question in Georgian.

    Returns:
        Tuple of (temporal_warning: bool, extracted_year: Optional[int]).
        If no year found, returns (False, None).
    """
    match = PAST_DATE_PATTERN.search(query)
    if match:
        year = int(match.group(1))
        return True, year
    return False, None
