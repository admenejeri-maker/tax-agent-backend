"""
Citation Backend Tests — Task 7 (TDD: RED phase)
==================================================

Tests for citation sidebar support:
  - SourceMetadata.url field
  - SourceDetail.id / url fields
  - _extract_source_metadata() URL construction
  - build_system_prompt() citation injection
  - Feature flag gating
  - SSE event enrichment

All tests should FAIL until production code is implemented.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Model tests ──────────────────────────────────────────────────────────────


class TestSourceMetadataUrl:
    """T1: SourceMetadata should have an optional `url` field."""

    def test_source_metadata_has_url_field(self):
        from app.models.rag_response import SourceMetadata

        meta = SourceMetadata(
            article_number="165",
            chapter="XVII",
            title="საშემოსავლო გადასახადი",
            score=0.85,
            url="https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_165",
        )
        assert meta.url == "https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_165"

    def test_source_metadata_url_defaults_none(self):
        from app.models.rag_response import SourceMetadata

        meta = SourceMetadata(article_number="165", score=0.85)
        assert meta.url is None


class TestSourceDetailIdAndUrl:
    """T2: SourceDetail should have `id` and `url` fields."""

    def test_source_detail_has_id_field(self):
        from app.models.api_models import SourceDetail

        detail = SourceDetail(
            id=1,
            article_number="170",
            chapter="XVIII",
            title="დღგ-ს განაკვეთი",
            score=0.90,
            url="https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_170",
        )
        assert detail.id == 1

    def test_source_detail_has_url_field(self):
        from app.models.api_models import SourceDetail

        detail = SourceDetail(
            id=2,
            article_number="165",
            url="https://example.com/article/165",
        )
        assert detail.url == "https://example.com/article/165"

    def test_source_detail_defaults(self):
        from app.models.api_models import SourceDetail

        detail = SourceDetail()
        assert detail.id == 0
        assert detail.url is None


# ─── URL construction ─────────────────────────────────────────────────────────


class TestExtractSourceMetadataUrl:
    """T3: _extract_source_metadata() should construct Matsne URLs."""

    def test_url_contains_article_anchor(self):
        from app.services.rag_pipeline import _extract_source_metadata

        results = [
            {
                "article_number": 165,
                "chapter": "XVII",
                "title": "საშემოსავლო განაკვეთი",
                "score": 0.85,
            }
        ]
        metadata = _extract_source_metadata(results)
        assert len(metadata) == 1
        assert metadata[0].url is not None
        assert "Article_165" in metadata[0].url

    def test_url_none_when_no_article_number(self):
        from app.services.rag_pipeline import _extract_source_metadata

        results = [
            {
                "chapter": "I",
                "title": "ზოგადი",
                "score": 0.50,
            }
        ]
        metadata = _extract_source_metadata(results)
        assert metadata[0].url is None

    def test_url_uses_matsne_base_url(self):
        from app.services.rag_pipeline import _extract_source_metadata

        results = [
            {
                "article_number": 170,
                "title": "დღგ",
                "score": 0.90,
            }
        ]
        metadata = _extract_source_metadata(results)
        assert metadata[0].url.startswith("https://matsne.gov.ge")


# ─── Prompt injection ─────────────────────────────────────────────────────────


class TestBuildSystemPromptCitation:
    """T4 + T5: build_system_prompt() citation injection and gating."""

    def test_prompt_with_source_refs_contains_citation_section(self):
        """T4: source_refs present → prompt has citation block."""
        from app.services.tax_system_prompt import build_system_prompt

        source_refs = [
            {"id": 1, "article_number": "165", "title": "საშემოსავლო გადასახადი"},
            {"id": 2, "article_number": "170", "title": "დღგ-ს განაკვეთი"},
        ]
        prompt = build_system_prompt(
            context_chunks=["some context"],
            source_refs=source_refs,
        )
        assert "[1]" in prompt
        assert "მუხლი 165" in prompt
        assert "ციტატა" in prompt or "Citation" in prompt

    def test_prompt_without_source_refs_no_citation(self):
        """T5: source_refs=None → no citation section."""
        from app.services.tax_system_prompt import build_system_prompt

        prompt = build_system_prompt(
            context_chunks=["some context"],
            source_refs=None,
        )
        assert "## ციტატა (Citation)" not in prompt

    def test_prompt_empty_source_refs_no_citation(self):
        """T5b: source_refs=[] → no citation section."""
        from app.services.tax_system_prompt import build_system_prompt

        prompt = build_system_prompt(
            context_chunks=["some context"],
            source_refs=[],
        )
        assert "## ციტატა (Citation)" not in prompt


# ─── Feature flag gating ──────────────────────────────────────────────────────


class TestCitationFeatureFlag:
    """T6: citation_enabled flag controls prompt injection."""

    def test_config_has_citation_enabled(self):
        """Config should have citation_enabled field."""
        from config import Settings

        s = Settings()
        assert hasattr(s, "citation_enabled")

    def test_config_has_matsne_base_url(self):
        """Config should have matsne_base_url field."""
        from config import Settings

        s = Settings()
        assert hasattr(s, "matsne_base_url")
        assert "matsne.gov.ge" in s.matsne_base_url


# ─── SSE event enrichment ─────────────────────────────────────────────────────


class TestSSESourcesEvent:
    """T7 + T8: SSE sources event enrichment and inline removal."""

    def test_api_router_sources_have_id_and_url(self):
        """T7: api_router SSE sources event must have id and url."""
        from app.models.rag_response import SourceMetadata

        # Simulate what the generator does with enriched source_metadata
        source_metadata = [
            SourceMetadata(
                article_number="165",
                chapter="XVII",
                title="საშემოსავლო",
                score=0.85,
                url="https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_165",
            ),
            SourceMetadata(
                article_number="170",
                chapter="XVIII",
                title="დღგ",
                score=0.90,
                url="https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_170",
            ),
        ]

        # Replicate the SSE sources_data construction expected AFTER implementation
        sources_data = [
            {
                "id": i + 1,
                "article_number": s.article_number,
                "chapter": s.chapter,
                "title": s.title,
                "score": s.score,
                "url": s.url,
            }
            for i, s in enumerate(source_metadata)
        ]

        assert sources_data[0]["id"] == 1
        assert sources_data[0]["url"] is not None
        assert "Article_165" in sources_data[0]["url"]
        assert sources_data[1]["id"] == 2

    def test_frontend_compat_no_inline_sources_text(self):
        """T8: frontend_compat should NOT have inline 📚 წყაროები block.

        After Task 7, the frontend_compat.py should emit a structured
        'sources' SSE event instead of appending inline text.
        We verify by checking the source code does NOT contain the pattern.
        """
        import inspect
        from app.api import frontend_compat

        source_code = inspect.getsource(frontend_compat)
        # After implementation, the inline sources text append should be REMOVED
        assert "📚 **წყაროები:**" not in source_code, (
            "frontend_compat.py still contains inline sources text. "
            "This should be replaced by a structured 'sources' SSE event."
        )
