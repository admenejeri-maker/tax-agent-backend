"""
Integration & E2E Tests — Task 6 (Final Sprint Gate)
=====================================================

5 tests that wire together all sprint components (Tasks 2-5, 7):
  E2E-1: Full pipeline flow — Rewrite -> Search -> Citation URLs
  E2E-2: SSE sources have id + url fields via HTTP
  E2E-3: SSE event sequence integrity
  E2E-4: Citation markers in answer
  E2E-5: Per-task acceptance gate (all task test files pass)
"""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


# ── Shared fixtures ──────────────────────────────────────────────────────────


def _make_search_result(article_number: int = 169, title: str = "დღგ-ს განაკვეთი") -> dict:
    """Create a search result dict matching hybrid_search() return format."""
    return {
        "article_number": article_number,
        "title": title,
        "body": f"მუხლი {article_number}: {title} — 18 პროცენტი.",
        "chapter": "XII",
        "kari": "XII",
        "tavi": "1",
        "score": 0.85,
    }


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().split("\n")
        event_type = None
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = line[6:]
        if event_type:
            events.append({"event": event_type, "data": data})
    return events


# ── Mock fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_auth():
    """Override verify_api_key for unauthenticated testing."""
    from app.auth.dependencies import verify_api_key

    async def _override():
        return {"user_id": "e2e_test_user", "key_hash": "e2e_hash", "is_active": True}

    app.dependency_overrides[verify_api_key] = _override
    yield
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_conv_store():
    """Mock conversation_store for session management."""
    with patch("app.api.api_router.conversation_store") as mock_store:
        mock_store.create_session = AsyncMock(return_value="e2e-session-001")
        mock_store.get_history = AsyncMock(return_value=None)
        mock_store.add_turn = AsyncMock()
        yield mock_store


@pytest.fixture
def mock_rag_pipeline():
    """Mock answer_question with a canned RAGResponse including citation data."""
    with patch("app.api.api_router.answer_question") as mock_aq:
        from app.models.rag_response import RAGResponse, SourceMetadata

        mock_aq.return_value = RAGResponse(
            answer="მუხლი 169 მიხედვით [1], დღგ-ს განაკვეთი შეადგენს 18%-ს.",
            source_metadata=[
                SourceMetadata(
                    article_number="169",
                    chapter="XII",
                    title="დღგ-ს განაკვეთი",
                    score=0.85,
                    url="https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_169",
                ),
            ],
            confidence_score=0.92,
            disclaimer=None,
            temporal_warning=None,
            error=None,
        )
        yield mock_aq


# =============================================================================
# E2E-1: Full Pipeline Flow — Rewrite → Search → Citation URLs
# =============================================================================


class TestFullPipelineFlow:
    """E2E-1: Verify the full RAG pipeline produces enriched source URLs."""

    @pytest.mark.asyncio
    @patch("app.services.rag_pipeline.get_genai_client")
    @patch("app.services.rag_pipeline.hybrid_search")
    @patch("app.services.rag_pipeline.rewrite_query", new_callable=AsyncMock)
    async def test_pipeline_produces_matsne_urls(
        self, mock_rewrite, mock_search, mock_genai
    ):
        """Full pipeline: rewrite → search → citation URL construction."""
        from app.services.rag_pipeline import answer_question

        # Mock rewriter: passes through (simulates no history)
        mock_rewrite.return_value = "რა არის დღგ-ს განაკვეთი?"

        # Mock search: returns article with article_number
        mock_result = _make_search_result(169, "დღგ-ს განაკვეთი")
        mock_search.return_value = [mock_result]

        # Mock LLM: returns answer with citation marker
        mock_response = MagicMock()
        mock_response.text = "მუხლი 169 მიხედვით [1], დღგ-ს განაკვეთი 18%-ია."
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.return_value = mock_client

        result = await answer_question("რა არის დღგ-ს განაკვეთი?")

        # Verify: answer returned, no error
        assert result.error is None
        assert len(result.answer) > 0

        # Verify: source_metadata has Matsne URL
        assert len(result.source_metadata) >= 1
        first_source = result.source_metadata[0]
        assert first_source.url is not None
        assert first_source.url.startswith("https://matsne.gov.ge")
        assert "Article_169" in first_source.url


# =============================================================================
# E2E-2: SSE Sources Have id + url Fields
# =============================================================================


class TestSSESourcesEnrichment:
    """E2E-2: SSE /ask/stream sources event must include id and url."""

    @pytest.mark.asyncio
    async def test_sse_sources_have_id_and_url(
        self, mock_auth, mock_conv_store, mock_rag_pipeline
    ):
        """SSE sources payload contains id (int) + url (string) per source."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask/stream",
                json={"question": "რა არის დღგ-ს განაკვეთი?"},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Find the sources event
        sources_events = [e for e in events if e["event"] == "sources"]
        assert len(sources_events) == 1, "Expected exactly one 'sources' SSE event"

        sources_data = sources_events[0]["data"]
        assert isinstance(sources_data, list)
        assert len(sources_data) >= 1

        for source in sources_data:
            assert "id" in source, "Source missing 'id' field"
            assert isinstance(source["id"], int), f"id should be int, got {type(source['id'])}"
            assert source["id"] >= 1, "id should be 1-indexed"
            assert "url" in source, "Source missing 'url' field"
            assert source["url"].startswith("https://"), f"url should start with https://, got {source['url']}"


# =============================================================================
# E2E-3: SSE Event Sequence Integrity
# =============================================================================


class TestSSEEventSequence:
    """E2E-3: SSE event sequence must be: thinking → sources → text… → done."""

    @pytest.mark.asyncio
    async def test_event_sequence_and_done_payload(
        self, mock_auth, mock_conv_store, mock_rag_pipeline
    ):
        """Verify SSE event ordering and done event payload."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask/stream",
                json={"question": "ტესტი"},
            )

        events = _parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]

        # First event must be thinking
        assert event_types[0] == "thinking", f"First event should be 'thinking', got '{event_types[0]}'"

        # Must contain sources and text
        assert "sources" in event_types, "Missing 'sources' event"
        assert "text" in event_types, "Missing 'text' event"

        # Last event must be done
        assert event_types[-1] == "done", f"Last event should be 'done', got '{event_types[-1]}'"

        # Done event payload
        done_data = events[-1]["data"]
        assert "conversation_id" in done_data, "done event missing conversation_id"
        assert "confidence_score" in done_data, "done event missing confidence_score"


# =============================================================================
# E2E-4: Citation Markers in Answer
# =============================================================================


class TestCitationMarkers:
    """E2E-4: Answer should contain [1] citation markers when sources present."""

    @pytest.mark.asyncio
    @patch("app.services.rag_pipeline.get_genai_client")
    @patch("app.services.rag_pipeline.hybrid_search")
    @patch("app.services.rag_pipeline.rewrite_query", new_callable=AsyncMock)
    async def test_answer_contains_citation_markers(
        self, mock_rewrite, mock_search, mock_genai
    ):
        """LLM answer with [1] marker is preserved through pipeline."""
        from app.services.rag_pipeline import answer_question

        mock_rewrite.return_value = "რა არის დღგ-ს განაკვეთი?"

        mock_result = _make_search_result(169, "დღგ-ს განაკვეთი")
        mock_search.return_value = [mock_result]

        mock_response = MagicMock()
        mock_response.text = "მუხლი 169 მიხედვით [1], დღგ-ს განაკვეთი 18%-ია."
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.return_value = mock_client

        result = await answer_question("რა არის დღგ-ს განაკვეთი?")

        assert "[1]" in result.answer, "Answer should contain citation marker [1]"


# =============================================================================
# E2E-5: Per-Task Acceptance Gate
# =============================================================================


class TestPerTaskAcceptanceGate:
    """E2E-5: Each sprint task's test file must pass independently."""

    @pytest.mark.parametrize(
        "test_file,task_name",
        [
            ("tests/test_system_prompt.py", "Task 2+3: System Prompt"),
            ("tests/test_query_rewriter.py", "Task 4: Query Rewriter"),
            ("tests/test_vector_search.py", "Task 5: Vector Search"),
            ("tests/test_citation_backend.py", "Task 7: Citation Backend"),
            ("tests/test_rag_pipeline.py", "Task 6c: RAG Pipeline"),
            ("tests/test_rag_integration.py", "Task 6e: RAG Integration"),
        ],
    )
    def test_task_tests_pass(self, test_file, task_name):
        """Each task's test file should exit with code 0 (all tests pass)."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd="/Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent",
            timeout=60,
        )
        assert result.returncode == 0, (
            f"{task_name} FAILED:\n{result.stdout[-500:]}\n{result.stderr[-500:]}"
        )
