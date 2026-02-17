"""
Test Models — Pydantic Validation Tests
=========================================

Pure validation tests — no MongoDB required.
Tests model construction, field constraints, embedding validation,
and ConfigDict behavior (extra="ignore" for MongoDB _id).
"""

import pytest
from pydantic import ValidationError

from app.models.tax_article import TaxArticle, TaxArticleStore, ArticleStatus
from app.models.definition import Definition, DefinitionStore


# =============================================================================
# TEST HELPERS
# =============================================================================


def make_valid_article(**overrides) -> TaxArticle:
    """Factory for valid TaxArticle instances. Override any field via kwargs."""
    defaults = {
        "article_number": 1,
        "kari": "კარი I",
        "tavi": "თავი I",
        "title": "საშემოსავლო გადასახადი",
        "body": "საქართველოს საგადასახადო კოდექსი — ტესტი",
    }
    defaults.update(overrides)
    return TaxArticle(**defaults)


def make_valid_definition(**overrides) -> Definition:
    """Factory for valid Definition instances. Override any field via kwargs."""
    defaults = {
        "term_ka": "გადასახადი",
        "definition": "სავალდებულო, უპირობო ფულადი შენატანი",
        "article_ref": 8,
    }
    defaults.update(overrides)
    return Definition(**defaults)


# =============================================================================
# TaxArticle — VALIDATION TESTS
# =============================================================================


class TestTaxArticleValidation:
    """Pydantic validation for the TaxArticle model."""

    def test_valid_article_minimal(self):
        """Valid article with only required fields."""
        article = make_valid_article()
        assert article.article_number == 1
        assert article.status == ArticleStatus.ACTIVE
        assert article.embedding is None
        assert article.related_articles == []
        assert article.is_exception is False

    def test_valid_article_all_fields(self):
        """Valid article with all optional fields populated."""
        embedding = [0.1] * 768
        article = make_valid_article(
            related_articles=[2, 3],
            is_exception=True,
            last_amended_date="2024-03-15",
            status=ArticleStatus.AMENDED,
            embedding=embedding,
            embedding_model="gemini-embedding-001",
            embedding_text="კარი I > თავი I > მუხლი 1: Test",
        )
        assert article.related_articles == [2, 3]
        assert article.is_exception is True
        assert article.last_amended_date == "2024-03-15"
        assert article.status == ArticleStatus.AMENDED
        assert len(article.embedding) == 768

    def test_article_number_too_low(self):
        """article_number=0 should fail (ge=1)."""
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            make_valid_article(article_number=0)

    def test_article_number_too_high(self):
        """article_number=501 should fail (le=500)."""
        with pytest.raises(ValidationError, match="less than or equal to 500"):
            make_valid_article(article_number=501)

    def test_body_too_short(self):
        """body='short' should fail (min_length=10)."""
        with pytest.raises(ValidationError, match="at least 10"):
            make_valid_article(body="short")

    def test_empty_title(self):
        """Empty title should fail (min_length=1)."""
        with pytest.raises(ValidationError):
            make_valid_article(title="")

    def test_embedding_wrong_dimensions(self):
        """Embedding with wrong dimensions should fail."""
        with pytest.raises(ValidationError, match="768 dimensions"):
            make_valid_article(embedding=[0.1] * 100)

    def test_embedding_correct_dimensions(self):
        """Embedding with exactly 768 dimensions should pass."""
        article = make_valid_article(embedding=[0.1] * 768)
        assert len(article.embedding) == 768

    def test_embedding_none_is_valid(self):
        """None embedding is valid (populated by pipeline later)."""
        article = make_valid_article(embedding=None)
        assert article.embedding is None

    def test_extra_ignore_handles_mongo_id(self):
        """ConfigDict(extra='ignore') should silently skip _id from MongoDB."""
        article = TaxArticle(
            _id="507f1f77bcf86cd799439011",
            article_number=1,
            kari="I",
            tavi="I",
            title="Test",
            body="A" * 20,
        )
        assert article.article_number == 1
        assert not hasattr(article, "_id")


class TestArticleStatus:
    """ArticleStatus enum validation."""

    def test_enum_values(self):
        """ArticleStatus should have exactly 3 values."""
        assert ArticleStatus.ACTIVE == "active"
        assert ArticleStatus.REPEALED == "repealed"
        assert ArticleStatus.AMENDED == "amended"

    def test_default_status(self):
        """Default status should be ACTIVE."""
        article = make_valid_article()
        assert article.status == ArticleStatus.ACTIVE

    def test_invalid_status(self):
        """Invalid status string should fail."""
        with pytest.raises(ValidationError):
            make_valid_article(status="deleted")


# =============================================================================
# Definition — VALIDATION TESTS
# =============================================================================


class TestDefinitionValidation:
    """Pydantic validation for the Definition model."""

    def test_valid_definition_minimal(self):
        """Valid definition with only required fields."""
        defn = make_valid_definition()
        assert defn.term_ka == "გადასახადი"
        assert defn.embedding is None

    def test_empty_term_ka(self):
        """Empty term_ka should fail (min_length=1)."""
        with pytest.raises(ValidationError):
            make_valid_definition(term_ka="")

    def test_definition_too_short(self):
        """Definition text too short should fail (min_length=5)."""
        with pytest.raises(ValidationError, match="at least 5"):
            make_valid_definition(definition="abc")

    def test_article_ref_zero(self):
        """article_ref=0 should fail (ge=1)."""
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            make_valid_definition(article_ref=0)

    def test_embedding_wrong_dimensions(self):
        """Embedding with wrong dimensions should fail."""
        with pytest.raises(ValidationError, match="768 dimensions"):
            make_valid_definition(embedding=[0.1] * 256)

    def test_extra_ignore_handles_mongo_id(self):
        """ConfigDict(extra='ignore') should silently skip _id from MongoDB."""
        defn = Definition(
            _id="507f1f77bcf86cd799439011",
            term_ka="ტესტი",
            definition="Test definition text here",
            article_ref=8,
        )
        assert defn.term_ka == "ტესტი"
        assert not hasattr(defn, "_id")

    def test_model_dump_roundtrip(self):
        """model_dump should produce a dict that can reconstruct the model."""
        original = make_valid_definition()
        dumped = original.model_dump()
        reconstructed = Definition(**dumped)
        assert reconstructed.term_ka == original.term_ka
        assert reconstructed.definition == original.definition
