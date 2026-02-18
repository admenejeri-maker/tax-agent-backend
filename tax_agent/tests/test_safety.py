"""
Safety & Truncation Defense — Tests
====================================

22 tests covering:
- Unit: safety settings configuration (1-4)
- Unit: check_safety_block detection (5-9b)
- Unit: build_generation_config builder (10-11)
- Integration: pipeline retry flow (12-17b)
- Stress: edge cases (18-20)
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.safety import (
    PRIMARY_SAFETY_SETTINGS,
    FALLBACK_SAFETY_SETTINGS,
    SAFETY_FALLBACK_MESSAGE,
    check_safety_block,
    build_generation_config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers: Mock Gemini response objects
# ═══════════════════════════════════════════════════════════════════════════════


def _mock_response(finish_reason="STOP", text="test answer", has_candidates=True):
    """Build a mock Gemini response with configurable finish_reason."""
    response = MagicMock()
    if not has_candidates:
        response.candidates = []
        response.text = ""
        return response

    candidate = MagicMock()
    candidate.finish_reason = finish_reason
    candidate.content = MagicMock()
    part = MagicMock()
    part.text = text
    candidate.content.parts = [part]

    response.candidates = [candidate]
    response.text = text
    return response


def _mock_blocked_response():
    """Build a mock Gemini response that triggers SAFETY block."""
    response = _mock_response(finish_reason="SAFETY", text="")
    response.text = ""
    return response


def _mock_response_text_raises():
    """Response where .text raises (some SDK versions on certain finish reasons)."""
    response = MagicMock()
    candidate = MagicMock()
    candidate.finish_reason = "OTHER"  # Not SAFETY or MAX_TOKENS
    part = MagicMock()
    part.text = "partial answer"
    candidate.content = MagicMock()
    candidate.content.parts = [part]
    response.candidates = [candidate]
    # .text raises ValueError
    type(response).text = property(lambda self: (_ for _ in ()).throw(ValueError("blocked")))
    return response


def _mock_truncated_response(text="truncated answer..."):
    """Response with finish_reason=MAX_TOKENS (truncation)."""
    response = _mock_response(finish_reason="MAX_TOKENS", text=text)
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Unit Tests: Safety Settings Configuration (1-4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSafetySettingsConfig:
    """Tests 1-4: Validate safety settings tiers."""

    def test_primary_settings_has_4_categories(self):
        """Test 1: Primary settings cover all 4 harm categories."""
        assert len(PRIMARY_SAFETY_SETTINGS) == 4

    def test_primary_all_block_only_high(self):
        """Test 2: All primary settings use BLOCK_ONLY_HIGH threshold."""
        for s in PRIMARY_SAFETY_SETTINGS:
            assert str(s.threshold) == "HarmBlockThreshold.BLOCK_ONLY_HIGH", (
                f"Expected BLOCK_ONLY_HIGH for {s.category}, got {s.threshold}"
            )

    def test_fallback_dangerous_content_off(self):
        """Test 3: Fallback has OFF for DANGEROUS_CONTENT."""
        dangerous = [
            s for s in FALLBACK_SAFETY_SETTINGS
            if str(s.category) == "HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT"
        ]
        assert len(dangerous) == 1
        assert str(dangerous[0].threshold) == "HarmBlockThreshold.OFF"

    def test_fallback_others_block_only_high(self):
        """Test 4: Fallback non-DANGEROUS categories stay BLOCK_ONLY_HIGH."""
        others = [
            s for s in FALLBACK_SAFETY_SETTINGS
            if str(s.category) != "HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT"
        ]
        assert len(others) == 3
        for s in others:
            assert str(s.threshold) == "HarmBlockThreshold.BLOCK_ONLY_HIGH"


# ═══════════════════════════════════════════════════════════════════════════════
# Unit Tests: check_safety_block Detection (5-9)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckSafetyBlock:
    """Tests 5-9: Safety block detection edge cases."""

    def test_normal_stop(self):
        """Test 5: STOP finish_reason → not blocked, text extracted."""
        response = _mock_response(finish_reason="STOP", text="hello world")
        is_blocked, reason, text = check_safety_block(response)
        assert not is_blocked
        assert text == "hello world"

    def test_safety_blocked(self):
        """Test 6: SAFETY finish_reason → blocked, empty text."""
        response = _mock_blocked_response()
        is_blocked, reason, text = check_safety_block(response)
        assert is_blocked
        assert reason == "finish_reason_safety"
        assert text == ""

    def test_no_candidates(self):
        """Test 7: Empty candidates list → blocked."""
        response = _mock_response(has_candidates=False)
        is_blocked, reason, text = check_safety_block(response)
        assert is_blocked
        assert reason == "no_candidates"

    def test_none_response(self):
        """Test 8: None response → blocked."""
        is_blocked, reason, text = check_safety_block(None)
        assert is_blocked
        assert reason == "no_response"
        assert text == ""

    def test_text_extraction_fallback(self):
        """Test 9: response.text raises → falls back to part extraction."""
        response = _mock_response_text_raises()
        is_blocked, reason, text = check_safety_block(response)
        assert not is_blocked
        assert text == "partial answer"

    def test_max_tokens_detected(self):
        """Test 9a: MAX_TOKENS finish_reason → blocked, partial text returned."""
        response = _mock_truncated_response(text="ნაწილობრივი პასუხი...")
        is_blocked, reason, text = check_safety_block(response)
        assert is_blocked
        assert reason == "finish_reason_max_tokens"
        assert text == "ნაწილობრივი პასუხი..."


# ═══════════════════════════════════════════════════════════════════════════════
# Unit Tests: build_generation_config (10-11)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildGenerationConfig:
    """Tests 10-11: Config builder with safety settings."""

    def test_primary_config_has_safety_key(self):
        """Test 10: Primary config includes safety_settings."""
        config = build_generation_config("sys", 0.2, 2048, "primary")
        assert "safety_settings" in config
        assert config["safety_settings"] is PRIMARY_SAFETY_SETTINGS
        assert config["system_instruction"] == "sys"
        assert config["temperature"] == 0.2
        assert config["max_output_tokens"] == 2048

    def test_fallback_config_uses_fallback_settings(self):
        """Test 11: Fallback config uses FALLBACK_SAFETY_SETTINGS."""
        config = build_generation_config("sys", 0.2, 2048, "fallback")
        assert config["safety_settings"] is FALLBACK_SAFETY_SETTINGS


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests: Pipeline Safety Retry (12-17)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineSafetyRetry:
    """Tests 12-17: End-to-end retry flow in rag_pipeline."""

    @pytest.fixture
    def _pipeline_mocks(self):
        """Common mocks for pipeline tests."""
        with (
            patch("app.services.rag_pipeline.hybrid_search") as mock_search,
            patch("app.services.rag_pipeline.get_genai_client") as mock_client,
            patch("app.services.rag_pipeline.rewrite_query", new_callable=AsyncMock) as mock_rw,
            patch("app.services.rag_pipeline.route_query") as mock_route,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
        ):
            # Setup: search returns results
            mock_search.return_value = [{
                "text": "Article 150 content",
                "article_number": "150",
                "chapter": "Test",
                "title": "Test Article",
                "score": 0.9,
            }]
            mock_rw.return_value = "rewritten query"
            mock_route.return_value = "tax"
            mock_logic.return_value = []

            yield {
                "client": mock_client,
                "search": mock_search,
            }

    @pytest.mark.asyncio
    async def test_attempt1_succeeds_no_retry(self, _pipeline_mocks):
        """Test 12: When attempt 1 succeeds, no retry needed."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response(
            text="ვერიფიცირებული პასუხი"
        )
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == "ვერიფიცირებული პასუხი"
        assert not result.safety_fallback
        # Only 1 call to generate_content (no retries)
        assert mock_genai.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_attempt1_blocked_attempt2_succeeds(self, _pipeline_mocks):
        """Test 13: Attempt 1 SAFETY → Attempt 2 succeeds with relaxed settings."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_blocked_response(),  # Attempt 1: SAFETY
            _mock_response(text="retry answer"),  # Attempt 2: success
        ]
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == "retry answer"
        assert result.safety_fallback is True
        assert mock_genai.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_attempt1_2_blocked_attempt3_succeeds(self, _pipeline_mocks):
        """Test 14: Attempts 1+2 SAFETY → Attempt 3 succeeds with backup model."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_blocked_response(),  # Attempt 1
            _mock_blocked_response(),  # Attempt 2
            _mock_response(text="backup model answer"),  # Attempt 3
        ]
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == "backup model answer"
        assert result.safety_fallback is True
        assert mock_genai.models.generate_content.call_count == 3

    @pytest.mark.asyncio
    async def test_all_3_blocked_returns_fallback_msg(self, _pipeline_mocks):
        """Test 15: All 3 attempts SAFETY → fallback message."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_blocked_response(),
            _mock_blocked_response(),
            _mock_blocked_response(),
        ]
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == SAFETY_FALLBACK_MESSAGE
        assert not result.safety_fallback

    @pytest.mark.asyncio
    async def test_exception_triggers_retry(self, _pipeline_mocks):
        """Test 16: Exception on attempt 1 → continues to attempt 2."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            Exception("API error"),  # Attempt 1: exception
            _mock_response(text="recovered answer"),  # Attempt 2: success
        ]
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == "recovered answer"
        assert result.safety_fallback is True

    @pytest.mark.asyncio
    async def test_max_tokens_triggers_retry(self, _pipeline_mocks):
        """Test 16b: MAX_TOKENS on attempt 1 → retries with more tokens."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_truncated_response("cut off..."),  # Attempt 1: truncated
            _mock_response(text="full answer"),  # Attempt 2: success
        ]
        _pipeline_mocks["client"].return_value = mock_genai

        result = await answer_question("test question")
        assert result.answer == "full answer"
        assert result.safety_fallback is True
        assert mock_genai.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_disabled_only_attempt1(self, _pipeline_mocks):
        """Test 17: safety_retry_enabled=False → only 1 attempt."""
        from app.services.rag_pipeline import answer_question

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_blocked_response()
        _pipeline_mocks["client"].return_value = mock_genai

        with patch("app.services.rag_pipeline.settings") as mock_settings:
            mock_settings.generation_model = "gemini-3-flash-preview"
            mock_settings.safety_fallback_model = "gemini-2.5-flash"
            mock_settings.temperature = 0.2
            mock_settings.max_output_tokens = 2048
            mock_settings.max_history_turns = 5
            mock_settings.safety_retry_enabled = False
            mock_settings.critic_enabled = False
            mock_settings.keyword_search_enabled = True
            mock_settings.similarity_threshold = 0.5
            mock_settings.search_limit = 5
            mock_settings.router_enabled = False
            mock_settings.logic_rules_enabled = False
            mock_settings.citation_enabled = False

            result = await answer_question("test question")
            # Should return fallback message (only 1 attempt, and it was blocked)
            assert result.answer == SAFETY_FALLBACK_MESSAGE
            assert mock_genai.models.generate_content.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Stress / Edge Case Tests (18-20)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSafetyEdgeCases:
    """Tests 18-20: Edge cases and stress scenarios."""

    def test_critic_regen_uses_safety_settings(self):
        """Test 18: Verify critic regen path uses build_generation_config."""
        # Structural test: verify the import and config usage exists
        import inspect
        from app.services.rag_pipeline import answer_question  # noqa: F811

        source = inspect.getsource(answer_question)
        # The critic regen block should use build_generation_config
        assert "regen_config = build_generation_config(" in source

    def test_query_rewriter_uses_safety_settings(self):
        """Test 19: Verify query_rewriter uses build_generation_config."""
        import inspect
        from app.services.query_rewriter import rewrite_query

        source = inspect.getsource(rewrite_query)
        assert "build_generation_config(" in source

    def test_fallback_message_is_georgian(self):
        """Test 20: Fallback message is in Georgian (user-facing)."""
        # Georgian Unicode range: U+10A0 to U+10FF (Mkhedruli)
        georgian_chars = [c for c in SAFETY_FALLBACK_MESSAGE if "\u10a0" <= c <= "\u10ff"]
        assert len(georgian_chars) > 10, "Fallback message should be primarily Georgian"
