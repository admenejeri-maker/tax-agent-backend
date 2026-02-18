"""
Tiered Query Router — Step 2 (Contextual Isolation Upgrade)
============================================================

Compound-rule-first routing with keyword fallback and semantic stub.
Maps Georgian tax queries to semantic domains:
  VAT, INDIVIDUAL_INCOME, CORPORATE_TAX, PROPERTY_TAX, ADMIN_PROCEDURAL, GENERAL.

Routing Priority:
  Tier 0: Compound rules (multi-keyword intent patterns, 0ms)
  Tier 1: Keyword scan (single-keyword matching, 0ms)
  Tier 2: Semantic fallback (stub — graceful degradation)
  Tier 3: Default → GENERAL
"""

from dataclasses import dataclass
from typing import Dict, List

import structlog

logger = structlog.get_logger(__name__)


# ─── Route Result ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteResult:
    """Immutable routing classification result."""

    domain: str  # "VAT", "INDIVIDUAL_INCOME", "CORPORATE_TAX", "PROPERTY_TAX", "ADMIN_PROCEDURAL", "GENERAL"
    confidence: float  # 0.0 - 1.0
    method: str  # "compound" | "keyword" | "semantic" | "default"


# ─── Compound Rules (Tier 0) ────────────────────────────────────────────────
# Multi-keyword intent patterns checked BEFORE simple keyword matching.
# Order matters: first match wins.

COMPOUND_RULES: List[dict] = [
    # LLC/company + loan → corporate tax (Estonian model)
    {
        "requires_all": ["სესხ"],
        "requires_any": ["შპს", "დირექტორ", "საწარმო", "პარტნიორ", "კომპანი"],
        "domain": "CORPORATE_TAX",
        "confidence": 0.95,
    },
    # Loan for individual → individual income
    {
        "requires_all": ["სესხ"],
        "requires_any": ["ფიზიკური პირ", "ბანკ", "იპოთეკ", "პირადი"],
        "domain": "INDIVIDUAL_INCOME",
        "confidence": 0.9,
    },
    # Salary/net calculation — requires salary indicator + net keyword
    {
        "requires_any": ["ხელზე", "ნეტო", "სუფთა"],
        "requires_all": ["ხელფას"],
        "domain": "INDIVIDUAL_INCOME",
        "confidence": 0.95,
    },
    # Net amount WITHOUT salary → still INDIVIDUAL_INCOME but lower confidence
    {
        "requires_any": ["ხელზე", "ნეტო"],
        "requires_all": [],
        "domain": "INDIVIDUAL_INCOME",
        "confidence": 0.7,
    },
]


# ─── Keyword Map (Tier 1) ───────────────────────────────────────────────────
# Georgian tax terms are unambiguous — keyword matching gives 100% precision.
# Module-level constant for easy expansion without code changes.

KEYWORD_MAP: Dict[str, List[str]] = {
    "VAT": ["დღგ", "დამატებული ღირებულების"],
    "INDIVIDUAL_INCOME": [
        "საშემოსავლო", "ფიზიკური პირ", "ხელფას",
        "ხელზე", "ნეტო", "სუფთა", "ავიღე",
        "თანამშრომელ", "დასაქმებულ",
    ],
    "CORPORATE_TAX": [
        "მოგების გადასახადი", "იურიდიული პირ", "დივიდენდ",
        "შპს", "საწარმო", "კომპანი",
    ],
    "PROPERTY_TAX": ["ქონების გადასახადი"],
    "EXCISE": ["აქციზ", "აქციზი"],
    "CUSTOMS": ["საბაჟო", "იმპორტ"],
    "MICRO_BUSINESS": ["მიკრობიზნეს", "მცირე ბიზნეს", "მიკრო"],
    "ADMIN_PROCEDURAL": ["ჯარიმა", "საურავი", "გასაჩივრება", "დავა", "შემოწმება", "ვადები"],
}


# ─── Route Function ──────────────────────────────────────────────────────────


async def route_query(query: str) -> RouteResult:
    """Route a tax query to a semantic domain.

    Tier 0: Compound rules (multi-keyword intent matching)
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

    # Tier 0: Compound rules (highest priority — intent patterns)
    for rule in COMPOUND_RULES:
        all_match = (
            all(kw in query_lower for kw in rule["requires_all"])
            if rule["requires_all"]
            else True
        )
        any_match = (
            any(kw in query_lower for kw in rule["requires_any"])
            if rule["requires_any"]
            else True
        )
        if all_match and any_match:
            domain = rule["domain"]
            logger.info(
                "route_compound_match",
                domain=domain,
                confidence=rule["confidence"],
                query=query[:50],
            )
            return RouteResult(
                domain=domain,
                confidence=rule["confidence"],
                method="compound",
            )

    # Tier 1: Keyword scan (multi-domain aware)
    matches: Dict[str, int] = {}
    for domain, keywords in KEYWORD_MAP.items():
        count = sum(1 for kw in keywords if kw in query_lower)
        if count > 0:
            matches[domain] = count

    if matches:
        if len(matches) == 1:
            domain = next(iter(matches))
            logger.info("route_keyword_match", domain=domain, query=query[:50])
            return RouteResult(domain=domain, confidence=1.0, method="keyword")
        sorted_matches = sorted(matches.items(), key=lambda x: x[1], reverse=True)
        if sorted_matches[0][1] > sorted_matches[1][1]:
            domain = sorted_matches[0][0]
            logger.info("route_keyword_best_match", domain=domain, matches=matches, query=query[:50])
            return RouteResult(domain=domain, confidence=0.8, method="keyword")
        logger.info("route_ambiguous", matches=matches, query=query[:50])
        return RouteResult(domain="GENERAL", confidence=0.5, method="keyword")

    # Tier 2: Semantic fallback (stub)
    # TODO: Load from data/router_exemplars.json, embed query, cosine similarity
    logger.debug("route_no_keyword_match", query=query[:50])

    # Tier 3: Default
    return RouteResult(domain="GENERAL", confidence=0.0, method="default")
