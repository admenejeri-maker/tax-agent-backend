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


async def test_route_keyword_income():
    """Georgian 'საშემოსავლო' keyword routes to INCOME_TAX domain."""
    result = await route_query("საშემოსავლო გადასახადი რამდენია?")
    assert result.domain == "INCOME_TAX"
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
