"""
Test Query Rewriter — Task 4
==============================

8 tests verifying contextual query rewriting:
- No history / empty history / single-turn → return original (3 guard tests)
- Multi-turn rewrite with mocked LLM (1 happy path)
- Timeout fallback (1 resilience)
- API error fallback (1 resilience)
- Empty response fallback (1 edge case)
- History formatting helper (1 unit)
"""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from app.services.query_rewriter import rewrite_query, _format_history


class TestRewriteQueryGuards:
    """Tests for early-return guard conditions."""

    @pytest.mark.asyncio
    async def test_no_history_returns_original(self):
        """No history → return original query unchanged."""
        result = await rewrite_query("რა არის დღგ?", history=None)
        assert result == "რა არის დღგ?"

    @pytest.mark.asyncio
    async def test_empty_history_returns_original(self):
        """Empty history list → return original query unchanged."""
        result = await rewrite_query("და რამდენია?", history=[])
        assert result == "და რამდენია?"

    @pytest.mark.asyncio
    async def test_single_turn_returns_original(self):
        """Single turn = first question, nothing to rewrite against."""
        history = [{"role": "user", "text": "რა არის დღგ?"}]
        result = await rewrite_query("და რამდენია?", history=history)
        assert result == "და რამდენია?"


class TestRewriteQueryHappyPath:
    """Tests for successful LLM-powered rewriting."""

    @pytest.mark.asyncio
    @patch("app.services.query_rewriter.get_genai_client")
    async def test_rewrites_with_history(self, mock_get_client):
        """Multi-turn history → LLM rewrites follow-up into standalone query."""
        mock_response = MagicMock()
        mock_response.text = "რამდენია დღგ-ს განაკვეთი საქართველოში?"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "text": "რა არის დღგ?"},
            {"role": "model", "text": "დღგ არის დამატებული ღირებულების გადასახადი."},
        ]
        result = await rewrite_query("და რამდენია?", history=history)
        assert "დღგ" in result
        assert len(result) > len("და რამდენია?")


class TestRewriteQueryResilience:
    """Tests for fail-safe fallback behavior."""

    @pytest.mark.asyncio
    @patch("app.services.query_rewriter.get_genai_client")
    async def test_timeout_returns_original(self, mock_get_client):
        """Timeout → return original query (never block pipeline)."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = asyncio.TimeoutError()
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "text": "რა არის დღგ?"},
            {"role": "model", "text": "დღგ არის..."},
        ]
        result = await rewrite_query("და რამდენია?", history=history)
        assert result == "და რამდენია?"

    @pytest.mark.asyncio
    @patch("app.services.query_rewriter.get_genai_client")
    async def test_api_error_returns_original(self, mock_get_client):
        """API error → return original query (fail-safe)."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API 500")
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "text": "რა არის დღგ?"},
            {"role": "model", "text": "დღგ არის..."},
        ]
        result = await rewrite_query("და რამდენია?", history=history)
        assert result == "და რამდენია?"

    @pytest.mark.asyncio
    @patch("app.services.query_rewriter.get_genai_client")
    async def test_empty_response_returns_original(self, mock_get_client):
        """LLM returns empty text → return original query."""
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        history = [
            {"role": "user", "text": "რა არის დღგ?"},
            {"role": "model", "text": "დღგ არის..."},
        ]
        result = await rewrite_query("და რამდენია?", history=history)
        assert result == "და რამდენია?"


class TestFormatHistory:
    """Tests for history formatting helper."""

    def test_format_history_labels(self):
        """Georgian role labels applied correctly."""
        history = [
            {"role": "user", "text": "კითხვა"},
            {"role": "model", "text": "პასუხი"},
        ]
        result = _format_history(history)
        assert "მომხმარებელი: კითხვა" in result
        assert "ასისტენტი: პასუხი" in result
