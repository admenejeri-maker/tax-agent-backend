"""
Router Unit Tests — Step 2
===========================

Tests for the tiered query router (keyword-first routing).
No mocking needed — router has no DB or API dependencies.
"""

import pytest

from app.services.router import route_query, RouteResult, KEYWORD_MAP


# ─── Keyword Routing ─────────────────────────────────────────────────────────


async def test_route_keyword_vat():
    """Georgian 'დღგ' keyword routes to VAT domain."""
    result = await route_query("რა არის დღგ?")
    assert result.domain == "VAT"
    assert result.confidence == 1.0
    assert result.method == "keyword"


async def test_route_keyword_individual_income():
    """Georgian 'საშემოსავლო' keyword routes to INDIVIDUAL_INCOME domain."""
    result = await route_query("საშემოსავლო გადასახადი რამდენია?")
    assert result.domain == "INDIVIDUAL_INCOME"
    assert result.confidence == 1.0
    assert result.method == "keyword"


async def test_route_keyword_property():
    """Georgian 'ქონების გადასახადი' keyword routes to PROPERTY_TAX domain."""
    result = await route_query("ქონების გადასახადი 2024")
    assert result.domain == "PROPERTY_TAX"
    assert result.confidence == 1.0
    assert result.method == "keyword"


# ─── Default / Edge Cases ────────────────────────────────────────────────────


async def test_route_default_general():
    """Unrecognized query falls through to GENERAL domain."""
    result = await route_query("hello general question")
    assert result.domain == "GENERAL"
    assert result.confidence == 0.0
    assert result.method == "default"


async def test_route_empty_query():
    """Empty query returns GENERAL default immediately."""
    result = await route_query("")
    assert result.domain == "GENERAL"
    assert result.confidence == 0.0
    assert result.method == "default"


# ─── Immutability ────────────────────────────────────────────────────────────


async def test_route_result_immutable():
    """RouteResult is frozen — mutation raises AttributeError."""
    result = await route_query("დღგ test")
    with pytest.raises(AttributeError):
        result.domain = "OTHER"


# ─── Bug #7: New domains ────────────────────────────────────────────────────


async def test_route_excise_query():
    """Bug #7: 'აქციზის განაკვეთი' routes to EXCISE domain."""
    result = await route_query("აქციზის განაკვეთი რამდენია?")
    assert result.domain == "EXCISE"
    assert result.confidence == 1.0
    assert result.method == "keyword"


# ─── Bug #1: Multi-domain keyword routing ───────────────────────────────────


async def test_route_multi_domain_ambiguous():
    """Bug #1: Query with equal keyword hits across domains → GENERAL."""
    # 'დღგ' → VAT (1 hit), 'საშემოსავლო' → INDIVIDUAL_INCOME (1 hit) = tie
    result = await route_query("დღგ და საშემოსავლო")
    assert result.domain == "GENERAL"
    assert result.confidence == 0.5
    assert result.method == "keyword"


async def test_route_multi_domain_dominant():
    """Bug #1: Query with dominant keyword hits → picks that domain."""
    # 'დღგ' + 'დამატებული ღირებულების' → VAT (2 hits) vs 'საშემოსავლო' → INDIVIDUAL (1 hit)
    result = await route_query("დღგ და დამატებული ღირებულების საშემოსავლო")
    assert result.domain == "VAT"
    assert result.confidence == 0.8
    assert result.method == "keyword"


# ─── Domain Split: INDIVIDUAL_INCOME / CORPORATE_TAX ────────────────────────


async def test_route_keyword_corporate_tax():
    """Georgian 'მოგების გადასახადი' keyword routes to CORPORATE_TAX."""
    result = await route_query("მოგების გადასახადის განაკვეთი")
    assert result.domain == "CORPORATE_TAX"
    assert result.confidence == 1.0
    assert result.method == "keyword"


async def test_route_salary_individual():
    """Georgian 'ხელფასის' keyword routes to INDIVIDUAL_INCOME."""
    result = await route_query("ხელფასის გადასახადი რამდენია?")
    assert result.domain == "INDIVIDUAL_INCOME"
    assert result.confidence == 1.0
    assert result.method == "keyword"


async def test_route_dividend_corporate():
    """D1: Dividend stays in CORPORATE_TAX (withholding at source)."""
    result = await route_query("დივიდენდის დაბეგვრა")
    assert result.domain == "CORPORATE_TAX"
    assert result.confidence == 1.0
    assert result.method == "keyword"


async def test_route_admin_penalty():
    """D2: ADMIN_PROCEDURAL keywords route correctly."""
    result = await route_query("რამდენია ჯარიმა?")
    assert result.domain == "ADMIN_PROCEDURAL"
    assert result.confidence == 1.0
    assert result.method == "keyword"


# ─── Stress Tests: Multi-Domain Keyword Overlap ─────────────────────────────


@pytest.mark.parametrize(
    "query, expected_domain, expected_confidence",
    [
        # Individual + Corporate tie → GENERAL
        ("ფიზიკური პირის მოგების გადასახადი", "GENERAL", 0.5),
        # Individual + Admin tie → GENERAL
        ("საშემოსავლო გადასახადი ჯარიმა", "GENERAL", 0.5),
        # VAT(1) + Customs(2) → Customs wins
        ("დღგ საბაჟო იმპორტი", "CUSTOMS", 0.8),
        # Micro(2) > Corporate(1) → MICRO_BUSINESS wins
        ("მიკრობიზნესის მოგების გადასახადი", "MICRO_BUSINESS", 0.8),
    ],
)
async def test_multi_domain_stress(
    query: str, expected_domain: str, expected_confidence: float
):
    """Stress: queries matching 2+ domains produce correct routing."""
    result = await route_query(query)
    assert result.domain == expected_domain
    assert result.confidence == expected_confidence
    assert result.method == "keyword"


# ─── Compound Rule Tests (Tier 0) ────────────────────────────────────────────


@pytest.mark.parametrize(
    "query, expected_domain, expected_confidence",
    [
        # Rule 1: LLC/company + loan → CORPORATE_TAX (0.95)
        ("შპს-მ სესხი გასცა დირექტორს", "CORPORATE_TAX", 0.95),
        # Rule 1 variant: partner loan
        ("პარტნიორზე გაცემული სესხი", "CORPORATE_TAX", 0.95),
        # Rule 2: individual + loan → INDIVIDUAL_INCOME (0.9)
        ("ფიზიკურმა პირმა სესხი აიღო ბანკიდან", "INDIVIDUAL_INCOME", 0.9),
        # Rule 3: salary + net → INDIVIDUAL_INCOME (0.95)
        ("2000 ხელზე რამდენი ხელფასია?", "INDIVIDUAL_INCOME", 0.95),
        # Rule 4: net ONLY (no salary keyword) → INDIVIDUAL_INCOME (0.7)
        ("ხელზე რამდენი დამრჩება ქირიდან", "INDIVIDUAL_INCOME", 0.7),
        # Rule 2 variant: bank loan for individual
        ("სესხი ბანკიდან", "INDIVIDUAL_INCOME", 0.9),
    ],
)
async def test_compound_rule_routing(
    query: str, expected_domain: str, expected_confidence: float
):
    """Compound rules (Tier 0) route correctly before keyword matching."""
    result = await route_query(query)
    assert result.domain == expected_domain
    assert result.confidence == expected_confidence
    assert result.method == "compound"


async def test_compound_priority_over_keyword():
    """Compound match (Tier 0) takes priority over keyword match (Tier 1).

    'სესხი' + 'შპს' triggers compound rule → CORPORATE_TAX even though
    'მოგების გადასახადი' would trigger CORPORATE_TAX via keyword too.
    Method should be 'compound', not 'keyword'.
    """
    result = await route_query("შპს-ს სესხი და მოგების გადასახადი")
    assert result.domain == "CORPORATE_TAX"
    assert result.method == "compound"
    assert result.confidence == 0.95


async def test_no_compound_match_falls_through():
    """Query with no compound match falls through to keyword (Tier 1)."""
    result = await route_query("მოგების გადასახადის განაკვეთი")
    assert result.domain == "CORPORATE_TAX"
    assert result.method == "keyword"
    assert result.confidence == 1.0

