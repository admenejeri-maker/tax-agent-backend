"""
Test Follow-Up Generator — Phase 1: Quick Replies
===================================================

6 tests covering the follow-up suggestion generator:

1. Happy path: returns suggestions with {title, payload} format
2. Feature flag disabled: skips generation entirely
3. Short answer: skips generation for answers < 50 chars
4. LLM timeout: returns empty list (fail-safe)
5. LLM returns malformed JSON: returns empty list
6. Markdown code fences: strips fences and parses JSON correctly
"""

import asyncio
import json
from unittest.mock import patch, MagicMock

import pytest

from app.services.follow_up_generator import (
    generate_follow_ups,
    _parse_suggestions,
)


# ── Helper fixtures ──────────────────────────────────────────────────────────

def _mock_genai_response(text: str) -> MagicMock:
    """Create a mock Gemini API response with given text."""
    mock = MagicMock()
    mock.text = text
    return mock


SAMPLE_FOLLOW_UPS = [
    {"title": "საშემოსავლო განაკვეთი", "payload": "რა არის საშემოსავლო გადასახადის განაკვეთი?"},
    {"title": "გამონაკლისები", "payload": "რა გამონაკლისები არსებობს საშემოსავლო გადასახადიდან?"},
    {"title": "დეკლარაცია", "payload": "როდის უნდა ჩავაბარო საშემოსავლო დეკლარაცია?"},
]

SAMPLE_ANSWER = (
    "საშემოსავლო გადასახადის განაკვეთი საქართველოში შეადგენს 20%-ს. "
    "ეს ეხება ფიზიკური პირების შემოსავალს, მათ შორის ხელფასს, "
    "პრემიებს და სხვა შემოსავლებს. არსებობს გარკვეული გამონაკლისები "
    "და შეღავათები, რომლებიც განსაზღვრულია საგადასახადო კოდექსით."
)


# ── Unit Tests: _parse_suggestions ───────────────────────────────────────────

class TestParseSuggestions:
    """Tests for the _parse_suggestions JSON parser."""

    def test_valid_json_array(self):
        """Valid JSON array returns normalized suggestions."""
        raw = json.dumps(SAMPLE_FOLLOW_UPS)
        result = _parse_suggestions(raw)
        assert len(result) == 3
        assert result[0]["title"] == "საშემოსავლო განაკვეთი"
        assert result[0]["payload"] == "რა არის საშემოსავლო გადასახადის განაკვეთი?"

    def test_markdown_code_fences_stripped(self):
        """Markdown code fences around JSON are stripped correctly."""
        raw = f"```json\n{json.dumps(SAMPLE_FOLLOW_UPS)}\n```"
        result = _parse_suggestions(raw)
        assert len(result) == 3

    def test_malformed_json_returns_empty(self):
        """Non-JSON text returns empty list."""
        result = _parse_suggestions("This is not JSON at all")
        assert result == []

    def test_non_array_json_returns_empty(self):
        """JSON object (not array) returns empty list."""
        result = _parse_suggestions('{"title": "test", "payload": "test"}')
        assert result == []

    def test_missing_fields_skipped(self):
        """Items missing title or payload are filtered out."""
        raw = json.dumps([
            {"title": "valid", "payload": "valid question"},
            {"title": "no payload"},
            {"payload": "no title"},
            {},
        ])
        result = _parse_suggestions(raw)
        assert len(result) == 1
        assert result[0]["title"] == "valid"

    def test_max_5_items(self):
        """Output is capped at 5 items even if LLM returns more."""
        items = [{"title": f"q{i}", "payload": f"question {i}"} for i in range(10)]
        raw = json.dumps(items)
        result = _parse_suggestions(raw)
        assert len(result) == 5


# ── Integration Tests: generate_follow_ups ───────────────────────────────────

class TestGenerateFollowUps:
    """Tests for the async generate_follow_ups function."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Returns suggestions when LLM responds with valid JSON."""
        mock_response = _mock_genai_response(json.dumps(SAMPLE_FOLLOW_UPS))
        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(return_value=mock_response)

        with patch("app.services.follow_up_generator.get_genai_client", return_value=mock_client), \
             patch("app.services.follow_up_generator.settings") as mock_settings:
            mock_settings.follow_up_enabled = True
            mock_settings.follow_up_model = "gemini-2.0-flash"
            mock_settings.follow_up_max_suggestions = 4
            mock_settings.follow_up_timeout = 3.0

            result = await generate_follow_ups(
                answer=SAMPLE_ANSWER,
                query="რა არის საშემოსავლო გადასახადი?",
            )

        assert len(result) == 3
        assert all("title" in r and "payload" in r for r in result)

    @pytest.mark.asyncio
    async def test_feature_flag_disabled(self):
        """Returns empty list when follow_up_enabled is False."""
        with patch("app.services.follow_up_generator.settings") as mock_settings:
            mock_settings.follow_up_enabled = False

            result = await generate_follow_ups(
                answer=SAMPLE_ANSWER,
                query="test query",
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_short_answer_skipped(self):
        """Returns empty list for answers shorter than 50 chars."""
        with patch("app.services.follow_up_generator.settings") as mock_settings:
            mock_settings.follow_up_enabled = True

            result = await generate_follow_ups(
                answer="მოკლე პასუხი",
                query="test query",
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """Returns empty list on LLM timeout (fail-safe)."""
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(side_effect=slow_call)

        with patch("app.services.follow_up_generator.get_genai_client", return_value=mock_client), \
             patch("app.services.follow_up_generator.settings") as mock_settings, \
             patch("app.services.follow_up_generator.asyncio") as mock_asyncio:
            mock_settings.follow_up_enabled = True
            mock_settings.follow_up_model = "gemini-2.0-flash"
            mock_settings.follow_up_max_suggestions = 4
            mock_settings.follow_up_timeout = 3.0
            mock_asyncio.wait_for = MagicMock(side_effect=asyncio.TimeoutError())
            mock_asyncio.TimeoutError = asyncio.TimeoutError
            mock_asyncio.to_thread = asyncio.to_thread

            result = await generate_follow_ups(
                answer=SAMPLE_ANSWER,
                query="test query",
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_api_error_returns_empty(self):
        """Returns empty list on API error (fail-safe)."""
        mock_client = MagicMock()
        mock_client.models.generate_content = MagicMock(
            side_effect=Exception("API quota exceeded")
        )

        with patch("app.services.follow_up_generator.get_genai_client", return_value=mock_client), \
             patch("app.services.follow_up_generator.settings") as mock_settings:
            mock_settings.follow_up_enabled = True
            mock_settings.follow_up_model = "gemini-2.0-flash"
            mock_settings.follow_up_max_suggestions = 4
            mock_settings.follow_up_timeout = 3.0

            result = await generate_follow_ups(
                answer=SAMPLE_ANSWER,
                query="test query",
            )

        assert result == []
