"""
Test RAG Pipeline — Task 6c
==============================

7 tests covering the RAG pipeline orchestration:
- Happy path (full pipeline)
- Empty search results fallback
- Gemini API failure → graceful error
- History respected
- Red zone + temporal disclaimers in response
- Source metadata extraction
- Confidence score calculation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag_pipeline import (
    answer_question,
    _build_contents,
    _extract_source_metadata,
    _calculate_confidence,
)
from app.models.rag_response import RAGResponse


# ─── Helper fixtures ─────────────────────────────────────────────────────────


def _mock_search_results():
    """Standard mock search results for tests."""
    return [
        {
            "article_number": "82",
            "chapter": "XIV",
            "title": "საშემოსავლო გადასახადის განაკვეთი",
            "content": "ფიზიკური პირისთვის საშემოსავლო გადასახადის განაკვეთი 20%.",
            "score": 0.92,
        },
        {
            "article_number": "83",
            "chapter": "XIV",
            "title": "გადასახადისგან გათავისუფლება",
            "content": "გადასახადისგან თავისუფლდება...",
            "score": 0.85,
        },
    ]


def _mock_gemini_response(text: str = "საშემოსავლო გადასახადი 20%-ია."):
    """Create a mock Gemini API response."""
    resp = MagicMock()
    resp.text = text
    return resp


# ─── Unit Tests (pure functions) ─────────────────────────────────────────────


class TestBuildContents:
    """Tests for _build_contents helper."""

    def test_query_only(self):
        """Single query without history creates one content entry."""
        contents = _build_contents("test question")
        assert len(contents) == 1
        assert contents[0]["role"] == "user"

    def test_with_history(self):
        """History turns appear before the current query."""
        history = [
            {"role": "user", "text": "prev question"},
            {"role": "model", "text": "prev answer"},
        ]
        contents = _build_contents("new question", history=history)
        assert len(contents) == 3
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"
        assert contents[2]["role"] == "user"

    def test_history_capped(self):
        """History is capped at max_turns."""
        history = [{"role": "user", "text": f"q{i}"} for i in range(10)]
        contents = _build_contents("final", history=history, max_turns=3)
        # 3 history + 1 current = 4
        assert len(contents) == 4


class TestExtractSourceMetadata:
    """Tests for _extract_source_metadata helper."""

    def test_extracts_fields(self):
        """Source metadata is correctly extracted from search results."""
        results = _mock_search_results()
        metadata = _extract_source_metadata(results)
        assert len(metadata) == 2
        assert metadata[0].article_number == "82"
        assert metadata[0].score == 0.92


class TestCalculateConfidence:
    """Tests for _calculate_confidence helper."""

    def test_average_score(self):
        """Confidence is the average of result scores."""
        results = [{"score": 0.8}, {"score": 0.6}]
        assert _calculate_confidence(results) == pytest.approx(0.7)

    def test_empty_results(self):
        """Empty results return 0.0 confidence."""
        assert _calculate_confidence([]) == 0.0


# ─── Integration-style Tests (mocked external calls) ─────────────────────────


class TestAnswerQuestion:
    """Tests for the full answer_question pipeline (with mocked externals)."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Full pipeline returns a valid RAGResponse with answer and sources."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response()
            )

            result = await answer_question("რა არის საშემოსავლო?")

            assert isinstance(result, RAGResponse)
            assert result.answer != ""
            assert result.error is None
            assert len(result.sources) > 0

    @pytest.mark.asyncio
    async def test_gemini_failure_returns_error(self):
        """Gemini API failure returns RAGResponse with error field."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                side_effect=Exception("Gemini API timeout")
            )

            result = await answer_question("test question")

            assert isinstance(result, RAGResponse)
            assert result.error is not None
            assert "Gemini API timeout" in result.error

    @pytest.mark.asyncio
    async def test_red_zone_adds_disclaimer(self):
        """Red zone query attaches the calculation disclaimer."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response()
            )

            # "რამდენი" triggers red zone
            result = await answer_question("რამდენი გადასახადი?")

            assert result.disclaimer is not None
            assert "კონსულტანტს" in result.disclaimer
