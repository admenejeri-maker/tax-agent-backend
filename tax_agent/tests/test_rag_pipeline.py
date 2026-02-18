"""
Test RAG Pipeline — Task 6c + Step 6 Wiring
=============================================

16 tests covering the RAG pipeline orchestration:

Original (9):
- Happy path (full pipeline)
- Gemini API failure → graceful error
- Red zone + temporal disclaimers in response
- Source metadata extraction
- Confidence score calculation
- Build contents helpers

Step 6 Wiring (7):
- BUG-1: kari field mapping fix (was chapter)
- Router wiring when enabled
- Router disabled defaults to GENERAL
- Logic rules injection into system prompt
- Critic approval passthrough
- Critic rejection appends warning
- Critic disabled passthrough
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


# ─── Step 6 Wiring Tests ─────────────────────────────────────────────────────


def _mock_search_results_kari():
    """Search results using kari (real field name) instead of chapter."""
    return [
        {
            "article_number": "82",
            "kari": "XIV",
            "title": "საშემოსავლო გადასახადის განაკვეთი",
            "body": "ფიზიკური პირისთვის საშემოსავლო გადასახადის განაკვეთი 20%.",
            "score": 0.92,
        },
    ]


class TestBugFixKariField:
    """BUG-1: _extract_source_metadata should read kari, not chapter."""

    def test_kari_mapped_to_chapter(self):
        """kari field from vector_search is mapped to chapter in SourceMetadata."""
        results = _mock_search_results_kari()
        metadata = _extract_source_metadata(results)
        assert metadata[0].chapter == "XIV"

    def test_old_chapter_field_ignored(self):
        """If result has chapter instead of kari, chapter should be None."""
        results = [
            {"article_number": "1", "chapter": "III", "title": "t", "score": 0.5}
        ]
        metadata = _extract_source_metadata(results)
        # After the fix, chapter field is ignored — only kari is read
        assert metadata[0].chapter is None


class TestRouterWiring:
    """Step 6: Router is invoked when router_enabled=True."""

    @pytest.mark.asyncio
    async def test_router_called_when_enabled(self):
        """route_query is called and domain is used when flag is on."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.route_query", new_callable=AsyncMock) as mock_router,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = True
            mock_settings.critic_enabled = False
            mock_settings.citation_enabled = False
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(return_value=_mock_gemini_response())

            from app.services.router import RouteResult
            mock_router.return_value = RouteResult(
                domain="VAT", confidence=1.0, method="keyword"
            )

            await answer_question("რა არის დღგ?")

            mock_router.assert_called_once()
            mock_logic.assert_called_once_with("VAT")

    @pytest.mark.asyncio
    async def test_router_disabled_uses_general(self):
        """When router_enabled=False, domain defaults to GENERAL."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.route_query", new_callable=AsyncMock) as mock_router,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = False
            mock_settings.citation_enabled = False
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(return_value=_mock_gemini_response())

            await answer_question("test")

            mock_router.assert_not_called()
            mock_logic.assert_called_once_with("GENERAL")


class TestLogicRulesInjection:
    """Step 6: logic_rules is passed to build_system_prompt."""

    @pytest.mark.asyncio
    async def test_logic_rules_passed_to_prompt(self):
        """build_system_prompt receives logic_rules argument."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.build_system_prompt") as mock_prompt,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = False
            mock_settings.citation_enabled = False
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = "## VAT Calculation Rules\n- Rate is 18%"
            mock_prompt.return_value = "system prompt"
            mock_asyncio.to_thread = AsyncMock(return_value=_mock_gemini_response())

            await answer_question("test")

            # Verify logic_rules= was in the kwargs
            call_kwargs = mock_prompt.call_args.kwargs
            assert call_kwargs["logic_rules"] == "## VAT Calculation Rules\n- Rate is 18%"


class TestCriticWiring:
    """Step 6: Critic is invoked when critic_enabled=True."""

    @pytest.mark.asyncio
    async def test_critic_approved_passthrough(self):
        """Approved critic result doesn't modify the answer."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.citation_enabled = True
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("Clean answer.")
            )

            from app.services.critic import CriticResult
            mock_critic.return_value = CriticResult(approved=True, feedback=None)

            result = await answer_question("test")

            mock_critic.assert_called_once()
            assert "⚠️" not in result.answer

    @pytest.mark.asyncio
    async def test_critic_rejected_appends_disclaimer(self):
        """Rejected critic result appends Georgian disclaimer (regen disabled)."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.critic_regeneration_enabled = False
            mock_settings.citation_enabled = True
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("Bad answer.")
            )

            from app.services.critic import CriticResult
            mock_critic.return_value = CriticResult(
                approved=False,
                feedback="Answer lacks source citations.",
            )

            result = await answer_question("test")

            assert "პასუხი შეიძლება არ იყოს სრულად ზუსტი" in result.answer
            assert "⚠️" not in result.answer

    @pytest.mark.asyncio
    async def test_regen_enabled_retries_on_rejection(self):
        """Regen enabled: critic rejects → retry → critic approves regen → clean answer."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.critic_regeneration_enabled = True
            mock_settings.citation_enabled = True
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None

            # Two Gemini calls: initial + regen
            mock_asyncio.to_thread = AsyncMock(side_effect=[
                _mock_gemini_response("Bad answer."),
                _mock_gemini_response("Improved answer."),
            ])

            from app.services.critic import CriticResult
            mock_critic.side_effect = [
                CriticResult(approved=False, feedback="Missing citations."),
                CriticResult(approved=True, feedback=None),
            ]

            result = await answer_question("test")

            assert result.answer == "Improved answer."
            assert "პასუხი" not in result.answer
            assert mock_asyncio.to_thread.call_count == 2
            assert mock_critic.call_count == 2

    @pytest.mark.asyncio
    async def test_regen_fallback_on_double_reject(self):
        """Regen enabled: critic rejects both initial and regen → Georgian disclaimer."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.critic_regeneration_enabled = True
            mock_settings.citation_enabled = True
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None

            mock_asyncio.to_thread = AsyncMock(side_effect=[
                _mock_gemini_response("Bad answer."),
                _mock_gemini_response("Still bad answer."),
            ])

            from app.services.critic import CriticResult
            mock_critic.side_effect = [
                CriticResult(approved=False, feedback="Missing citations."),
                CriticResult(approved=False, feedback="Still wrong."),
            ]

            result = await answer_question("test")

            assert "პასუხი შეიძლება არ იყოს სრულად ზუსტი" in result.answer
            assert mock_asyncio.to_thread.call_count == 2
            assert mock_critic.call_count == 2

    @pytest.mark.asyncio
    async def test_regen_disabled_uses_disclaimer(self):
        """Regen disabled: critic rejects → Georgian disclaimer, 1 Gemini call only."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.critic_regeneration_enabled = False
            mock_settings.citation_enabled = True
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("Bad answer.")
            )

            from app.services.critic import CriticResult
            mock_critic.return_value = CriticResult(
                approved=False,
                feedback="Answer lacks source citations.",
            )

            result = await answer_question("test")

            assert "პასუხი შეიძლება არ იყოს სრულად ზუსტი" in result.answer
            assert mock_asyncio.to_thread.call_count == 1
            mock_critic.assert_called_once()

    @pytest.mark.asyncio
    async def test_critic_disabled_not_called(self):
        """When critic_enabled=False, critique_answer is never called."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = False
            mock_settings.citation_enabled = False
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(return_value=_mock_gemini_response())

            await answer_question("test")

            mock_critic.assert_not_called()


# ─── Bug #10: PII sanitization in error logs ────────────────────────────────


class TestPIISanitization:
    """Tests for the _sanitize_for_log PII scrubber."""

    def test_pii_scrubbed_from_error_log(self):
        """Bug #10: Digit sequences of 5+ chars are redacted in log output."""
        from app.services.rag_pipeline import _sanitize_for_log

        # Phone number / ID number redacted
        result = _sanitize_for_log("ჩემი ID არის 12345678901 და")
        assert "[REDACTED]" in result
        assert "12345678901" not in result

    def test_short_numbers_not_redacted(self):
        """Short digit sequences (< 5 chars) should pass through."""
        from app.services.rag_pipeline import _sanitize_for_log

        result = _sanitize_for_log("2022 წელს გავყიდე 1234 ლარი")
        assert "2022" in result
        assert "1234" in result

    def test_sanitize_truncates_to_max_len(self):
        """Output is truncated to max_len."""
        from app.services.rag_pipeline import _sanitize_for_log

        long_query = "ა" * 200
        result = _sanitize_for_log(long_query, max_len=50)
        assert len(result) == 50


# ─── Bug #6: Critic skipped when no sources ──────────────────────────────────


class TestCriticSkippedNoSources:
    """Bug #6: Critic should be skipped when citations are disabled."""

    @pytest.mark.asyncio
    async def test_critic_skipped_when_no_sources(self):
        """Bug #6: critic_enabled=True but citation_enabled=False → critic NOT called."""
        with (
            patch("app.services.rag_pipeline.hybrid_search", new_callable=AsyncMock) as mock_search,
            patch("app.services.rag_pipeline.resolve_terms", new_callable=AsyncMock) as mock_terms,
            patch("app.services.rag_pipeline.get_logic_rules") as mock_logic,
            patch("app.services.rag_pipeline.critique_answer", new_callable=AsyncMock) as mock_critic,
            patch("app.services.rag_pipeline.get_genai_client"),
            patch("app.services.rag_pipeline.asyncio") as mock_asyncio,
            patch("app.services.rag_pipeline.settings") as mock_settings,
        ):
            mock_settings.router_enabled = False
            mock_settings.critic_enabled = True
            mock_settings.citation_enabled = False  # No sources → critic skipped
            mock_settings.generation_model = "test-model"
            mock_settings.generation_temperature = 0.3
            mock_settings.generation_max_tokens = 1024

            mock_search.return_value = _mock_search_results_kari()
            mock_terms.return_value = []
            mock_logic.return_value = None
            mock_asyncio.to_thread = AsyncMock(
                return_value=_mock_gemini_response("No-source answer.")
            )

            result = await answer_question("test")

            mock_critic.assert_not_called()
            assert "⚠️" not in result.answer
