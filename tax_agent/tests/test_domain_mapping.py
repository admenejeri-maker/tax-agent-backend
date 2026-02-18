"""
Domain Mapping Tests — Boundary Value Analysis
=================================================

Tests for get_domain() function and TaxArticle domain field.
Uses parametrized boundary-value testing to verify every
article→domain transition in the Georgian Tax Code.
"""

import pytest

from app.services.matsne_scraper import get_domain
from app.models.tax_article import TaxArticle


# ─── get_domain() Boundary Tests ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "article_number, expected_domain",
    [
        # Edge: below known ranges
        (0, "GENERAL"),
        (78, "GENERAL"),
        # Individual Income start
        (79, "INDIVIDUAL_INCOME"),
        (83, "INDIVIDUAL_INCOME"),
        # Micro Business
        (84, "MICRO_BUSINESS"),
        (95, "MICRO_BUSINESS"),
        # Corporate Tax — Estonian model (D3)
        (96, "CORPORATE_TAX"),
        (98, "CORPORATE_TAX"),
        # Back to Individual Income
        (99, "INDIVIDUAL_INCOME"),
        (123, "INDIVIDUAL_INCOME"),
        # Corporate Tax main
        (124, "CORPORATE_TAX"),
        (155, "CORPORATE_TAX"),
        # VAT
        (156, "VAT"),
        (181, "VAT"),
        # Excise
        (182, "EXCISE"),
        (194, "EXCISE"),
        # Customs
        (195, "CUSTOMS"),
        (199, "CUSTOMS"),
        # Property Tax
        (200, "PROPERTY_TAX"),
        (206, "PROPERTY_TAX"),
        # General (tax code admin)
        (207, "GENERAL"),
        (237, "GENERAL"),
        # Admin Procedural
        (238, "ADMIN_PROCEDURAL"),
        (310, "ADMIN_PROCEDURAL"),
        # Edge: beyond known ranges
        (311, "GENERAL"),
        (999, "GENERAL"),
    ],
)
def test_get_domain_boundaries(article_number: int, expected_domain: str):
    """Boundary-value test: each range transition maps correctly."""
    assert get_domain(article_number) == expected_domain


# ─── TaxArticle Domain Field ────────────────────────────────────────────────


def test_tax_article_domain_default():
    """TaxArticle.domain defaults to 'GENERAL' when not specified."""
    article = TaxArticle(
        article_number=1,
        kari="კარი I",
        tavi="თავი 1",
        title="Test",
        body="A" * 10,  # min_length=10
    )
    assert article.domain == "GENERAL"


def test_tax_article_domain_explicit():
    """TaxArticle.domain preserves explicit value."""
    article = TaxArticle(
        article_number=100,
        kari="კარი V",
        tavi="თავი 14",
        title="Test",
        body="A" * 10,
        domain="VAT",
    )
    assert article.domain == "VAT"
