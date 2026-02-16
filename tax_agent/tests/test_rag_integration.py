"""
RAG Integration Tests — Task 6e
=================================

End-to-end tests that exercise the full RAG pipeline with mocked externals.
Tests verify the interaction between classifiers → search → prompt → generation.

All LLM and DB calls are mocked (no real API keys needed).
For live testing, use @pytest.mark.live marker.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag_pipeline import answer_question
from app.models.rag_response import RAGResponse


# ─── Shared helpers ──────────────────────────────────────────────────────────


def _mock_search_results():
    """Standard mock search results."""
    return [
        {
            "article_number": "82",
            "chapter": "XIV",
            "title": "საშემოსავლო გადასახადის განაკვეთი",
            "content": "ფიზიკური პირისთვის საშემოსავლო გადასახადის განაკვეთი 20%.",
            "score": 0.92,
        },
    ]


def _mock_gemini_response(text: str):
    """Create a mock Gemini response object."""
    resp = MagicMock()
    resp.text = text
    return resp


# ─── Integration Tests ──────────────────────────────────────────────────────


class TestRAGIntegration:
    """Integration tests exercising the full pipeline flow."""

    @pytest.mark.asyncio
    async def test_informational_query_no_disclaimers(self):
        """Pure informational query should have no disclaimers."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("საშემოსავლო 20%-ია (მუხლი 82).")
            )

            result = await answer_question("რა არის საშემოსავლო გადასახადის განაკვეთი?")

            assert isinstance(result, RAGResponse)
            assert result.answer != ""
            assert result.error is None
            assert result.disclaimer is None
            assert result.temporal_warning is None
            assert "82" in result.sources

    @pytest.mark.asyncio
    async def test_calculation_query_triggers_disclaimer(self):
        """'რამდენი' query triggers red zone disclaimer but still answers."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("გადასახადი 20%-ია.")
            )

            result = await answer_question("რამდენი გადასახადი უნდა გადავიხადო?")

            assert result.disclaimer is not None
            assert result.answer != ""
            assert result.error is None

    @pytest.mark.asyncio
    async def test_temporal_query_triggers_warning(self):
        """'2022 წელს' query triggers temporal warning."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("2022 წელს განაკვეთი 20% იყო.")
            )

            result = await answer_question("2022 წელს რა იყო საშემოსავლო?")

            assert result.temporal_warning is not None
            assert "2022" in result.temporal_warning

    @pytest.mark.asyncio
    async def test_search_failure_graceful_degradation(self):
        """Search failure doesn't crash — returns error RAGResponse."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
        ):
            mock_search.side_effect = Exception("MongoDB connection timeout")
            mock_terms.return_value = []

            result = await answer_question("რა არის დღგ?")

            assert isinstance(result, RAGResponse)
            assert result.error is not None
            assert "MongoDB" in result.error

    @pytest.mark.asyncio
    async def test_with_conversation_history(self):
        """Multi-turn conversation passes history to the model."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client_fn,
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
        ):
            mock_search.return_value = _mock_search_results()
            mock_terms.return_value = []
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("დიახ, 20% გადასახადი მოქმედებს.")
            )

            history = [
                {"role": "user", "text": "რა არის საშემოსავლო?"},
                {"role": "model", "text": "საშემოსავლო 20%-ია."},
            ]

            result = await answer_question(
                "ეს ყველა მოქალაქეზეა?",
                history=history,
            )

            assert result.answer != ""
            assert result.error is None
