"""
Test Classifiers — Task 6a
============================

6 tests covering the 3 pre-retrieval classifiers:
- Red Zone Classifier (2 tests)
- Past-Date Detector (2 tests)
- Term Resolver (2 tests, async)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.classifiers import (
    classify_red_zone,
    resolve_terms,
    detect_past_date,
)


# ─── Red Zone Classifier ────────────────────────────────────────────────────


class TestClassifyRedZone:
    """Tests for the Red Zone (calculation/amount) classifier."""

    def test_calculation_query_triggers_red_zone(self):
        """'რამდენია საშემოსავლო?' asks 'how much' → Red Zone = True."""
        assert classify_red_zone("რამდენია საშემოსავლო?") is True

    def test_informational_query_not_red_zone(self):
        """'რა არის დღგ?' asks 'what is VAT' → informational → Red Zone = False."""
        assert classify_red_zone("რა არის დღგ?") is False


# ─── Past-Date Detector ─────────────────────────────────────────────────────


class TestDetectPastDate:
    """Tests for the past-year reference detector."""

    def test_year_in_query_detected(self):
        """'2022 წელს გავყიდე' contains year 2022 → temporal_warning=True."""
        warning, year = detect_past_date("2022 წელს გავყიდე")
        assert warning is True
        assert year == 2022

    def test_no_year_digits_not_detected(self):
        """'მომავალ წელს' has no digits → temporal_warning=False."""
        warning, year = detect_past_date("მომავალ წელს")
        assert warning is False
        assert year is None

    def test_detect_past_date_future_year(self):
        """Bug #9: Future year '2099 წელს' should NOT trigger temporal warning."""
        warning, year = detect_past_date("2099 წელს რა იქნება?")
        assert warning is False
        assert year is None

    def test_detect_past_date_current_year(self):
        """Bug #9: Current year should NOT trigger temporal warning."""
        import datetime
        current = datetime.datetime.now().year
        warning, year = detect_past_date(f"{current} წელს მაინტერესებს")
        assert warning is False
        assert year is None


# ─── Term Resolver ───────────────────────────────────────────────────────────


class TestResolveTerms:
    """Tests for the async term resolver (matches query against definitions DB)."""

    @pytest.mark.asyncio
    async def test_known_term_resolved(self):
        """Query containing 'ინდივიდუალური მეწარმე' matches a definition."""
        mock_defs = [
            {"term_ka": "ინდივიდუალური მეწარმე", "definition": "ფიზიკური პირი..."},
            {"term_ka": "დღგ", "definition": "დამატებული ღირებულების გადასახადი"},
        ]
        with patch(
            "app.services.classifiers.DefinitionStore"
        ) as MockStore:
            instance = MockStore.return_value
            instance.find_all = AsyncMock(return_value=mock_defs)

            result = await resolve_terms("ინდივიდუალური მეწარმე რა გადასახადი აქვს?")

            assert len(result) == 1
            assert result[0]["term_ka"] == "ინდივიდუალური მეწარმე"

    @pytest.mark.asyncio
    async def test_no_matching_term_returns_empty(self):
        """Query without any known tax term → resolver returns []."""
        mock_defs = [
            {"term_ka": "დღგ", "definition": "დამატებული ღირებულების გადასახადი"},
        ]
        with patch(
            "app.services.classifiers.DefinitionStore"
        ) as MockStore:
            instance = MockStore.return_value
            instance.find_all = AsyncMock(return_value=mock_defs)

            result = await resolve_terms("რაიმე ზოგადი კითხვა")

            assert result == []
