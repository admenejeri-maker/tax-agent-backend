"""
API Route Tests — Task 7
=========================

Tests for all API endpoints:
  POST /api/ask              — Sync RAG
  POST /api/ask/stream       — SSE streaming
  GET  /api/articles/{number} — Article lookup
  GET  /api/sessions         — List sessions
  GET  /api/session/{id}/history — Load conversation
  POST /api/session/clear    — Delete conversation
  GET  /api/health           — Enhanced health

All tests mock verify_api_key, conversation_store, answer_question,
and db_manager to isolate API layer logic.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from httpx import AsyncClient, ASGITransport
from main import app


# ── Fixtures ────────────────────────────────────────────────────────────────


MOCK_KEY_DOC = {
    "user_id": "test_user_42",
    "key_hash": "abc123hash",
    "key_prefix": "tk_abc12",
    "is_active": True,
}


@pytest.fixture
def mock_auth():
    """Override verify_api_key dependency to return a test key_doc."""
    from app.auth.dependencies import verify_api_key

    async def _override():
        return MOCK_KEY_DOC

    app.dependency_overrides[verify_api_key] = _override
    yield MOCK_KEY_DOC
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_conv_store():
    """Mock the conversation_store singleton used by the API router."""
    with patch("app.api.api_router.conversation_store") as mock_store:
        mock_store.create_session = AsyncMock(return_value="conv_new_123")
        mock_store.get_history = AsyncMock(return_value=None)
        mock_store.add_turn = AsyncMock()
        mock_store.list_sessions = AsyncMock(return_value=[])
        mock_store.clear_session = AsyncMock(return_value=True)
        yield mock_store


@pytest.fixture
def mock_rag_pipeline():
    """Mock the answer_question function with a canned RAGResponse."""
    with patch("app.api.api_router.answer_question") as mock_aq:
        mock_response = MagicMock()
        mock_response.answer = "დღგ-ს განაკვეთი შეადგენს 18 პროცენტს."
        mock_response.error = None
        mock_response.confidence_score = 0.92
        mock_response.disclaimer = "ეს არის საინფორმაციო პასუხი."
        mock_response.temporal_warning = None
        mock_response.sources = ["მუხლი 169"]

        # Mock source_metadata as list of objects with attributes
        mock_src = MagicMock()
        mock_src.article_number = "169"
        mock_src.chapter = "XII"
        mock_src.title = "დღგ-ს განაკვეთი"
        mock_src.score = 0.85
        mock_src.url = "https://matsne.gov.ge/ka/document/view/1043717/most-current-version#Article_169"
        mock_response.source_metadata = [mock_src]

        mock_aq.return_value = mock_response
        yield mock_aq, mock_response


# =============================================================================
# POST /api/ask — Sync RAG
# =============================================================================


class TestAskEndpoint:
    """Tests for POST /api/ask — synchronous RAG question."""

    @pytest.mark.asyncio
    async def test_ask_new_conversation(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should create a new session and return RAG answer."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask",
                json={"question": "რა არის დღგ-ს განაკვეთი?"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["conversation_id"] == "conv_new_123"
        assert data["confidence_score"] == 0.92
        assert len(data["sources"]) == 1
        assert data["sources"][0]["article_number"] == "169"
        mock_conv_store.create_session.assert_awaited_once_with("test_user_42")

    @pytest.mark.asyncio
    async def test_ask_resume_conversation(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should load history when conversation_id is provided."""
        mock_conv_store.get_history.return_value = {
            "conversation_id": "conv_existing",
            "turns": [
                {"role": "user", "content": "წინა კითხვა"},
                {"role": "assistant", "content": "წინა პასუხი"},
            ],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask",
                json={
                    "question": "კიდევ რა?",
                    "conversation_id": "conv_existing",
                },
            )

        assert resp.status_code == 200
        mock_conv_store.get_history.assert_awaited_once_with("conv_existing", "test_user_42")

    @pytest.mark.asyncio
    async def test_ask_conversation_not_found(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should return 404 if conversation_id does not exist for this user."""
        mock_conv_store.get_history.return_value = None

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask",
                json={
                    "question": "test",
                    "conversation_id": "nonexistent_id",
                },
            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_ask_empty_question_rejected(self, mock_auth):
        """Should reject empty question with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/ask", json={"question": ""})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ask_whitespace_question_rejected(self, mock_auth):
        """Should reject whitespace-only question with 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/ask", json={"question": "   "})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ask_requires_auth(self):
        """Should return 401 without API key header when REQUIRE_API_KEY=true."""
        # Ensure no auth override is present
        from app.auth.dependencies import verify_api_key
        app.dependency_overrides.pop(verify_api_key, None)

        with patch("app.auth.dependencies.api_key_store") as mock_store, \
             patch("config.settings") as mock_settings:
            mock_store.validate_key = AsyncMock(return_value=None)
            mock_settings.require_api_key = True
            # Copy other needed settings
            mock_settings.rate_limit = 30
            mock_settings.allowed_origins = ["*"]

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/ask",
                    json={"question": "test"},
                )

        # No X-API-Key header + REQUIRE_API_KEY=true → 401
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_ask_rag_error_returns_500(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should return 500 when RAG pipeline returns an error."""
        _, mock_response = mock_rag_pipeline
        mock_response.error = "LLM generation failed"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask",
                json={"question": "test question"},
            )

        assert resp.status_code == 500
        assert "LLM generation failed" in resp.json()["detail"]


# =============================================================================
# POST /api/ask/stream — SSE Streaming
# =============================================================================


class TestStreamEndpoint:
    """Tests for POST /api/ask/stream — SSE streaming RAG."""

    @pytest.mark.asyncio
    async def test_stream_returns_sse_events(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should return SSE events with correct format."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask/stream",
                json={"question": "რა არის დღგ-ს განაკვეთი?"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Parse SSE events
        text = resp.text
        events = []
        for block in text.strip().split("\n\n"):
            lines = block.strip().split("\n")
            event_type = None
            data = None
            for line in lines:
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            if event_type:
                events.append({"event": event_type, "data": data})

        # Verify event sequence: thinking → sources → (disclaimer?) → text… → done
        event_types = [e["event"] for e in events]
        assert event_types[0] == "thinking"
        assert "sources" in event_types
        assert "text" in event_types
        assert event_types[-1] == "done"

    @pytest.mark.asyncio
    async def test_stream_has_no_cache_headers(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """SSE response should include no-cache headers."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask/stream",
                json={"question": "test"},
            )

        assert resp.headers.get("cache-control") == "no-cache"

    @pytest.mark.asyncio
    async def test_stream_conversation_not_found(self, mock_auth, mock_conv_store, mock_rag_pipeline):
        """Should yield error event for nonexistent conversation."""
        mock_conv_store.get_history.return_value = None

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/ask/stream",
                json={
                    "question": "test",
                    "conversation_id": "nonexistent",
                },
            )

        assert resp.status_code == 200  # SSE always 200
        text = resp.text
        assert "error" in text
        assert "NOT_FOUND" in text


# =============================================================================
# GET /api/articles/{number} — Article Lookup
# =============================================================================


class TestArticleLookup:
    """Tests for GET /api/articles/{number}."""

    @pytest.mark.asyncio
    async def test_find_article_by_number(self, mock_auth):
        """Should return article data when found."""
        mock_article = {
            "article_number": 169,
            "title_ka": "დღგ-ს განაკვეთი",
            "title_en": "VAT Rate",
            "body_ka": "დღგ-ს განაკვეთი არის 18 პროცენტი.",
            "body_en": "VAT rate is 18 percent.",
            "kari": "XII",
            "tavi": "1",
        }

        with patch("app.api.api_router.db_manager") as mock_db:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=mock_article)
            mock_db.db.__getitem__ = MagicMock(return_value=mock_collection)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/articles/169")

        assert resp.status_code == 200
        data = resp.json()
        assert data["article_number"] == 169
        assert data["title_ka"] == "დღგ-ს განაკვეთი"

    @pytest.mark.asyncio
    async def test_article_not_found(self, mock_auth):
        """Should return 404 when article doesn't exist."""
        with patch("app.api.api_router.db_manager") as mock_db:
            mock_collection = AsyncMock()
            mock_collection.find_one = AsyncMock(return_value=None)
            mock_db.db.__getitem__ = MagicMock(return_value=mock_collection)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/articles/100")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_article_number_out_of_range(self, mock_auth):
        """Should return 422 for article number outside 1-500."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/articles/501")

        assert resp.status_code == 422
        assert "between 1 and 500" in resp.json()["detail"]


# =============================================================================
# GET /api/sessions — List Sessions
# =============================================================================


class TestListSessions:
    """Tests for GET /api/sessions."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, mock_auth, mock_conv_store):
        """Should return empty list when user has no sessions."""
        mock_conv_store.list_sessions.return_value = []

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/sessions")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_sessions_with_data(self, mock_auth, mock_conv_store):
        """Should return session summaries for the authenticated user."""
        mock_conv_store.list_sessions.return_value = [
            {
                "conversation_id": "conv_1",
                "title": "საუბარი დღგ-ზე",
                "turn_count": 4,
                "created_at": "2026-02-16T12:00:00",
                "updated_at": "2026-02-16T13:00:00",
            },
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["conversation_id"] == "conv_1"
        assert data[0]["turn_count"] == 4
        # Verify IDOR: only requested for this user
        mock_conv_store.list_sessions.assert_awaited_once_with("test_user_42")


# =============================================================================
# GET /api/session/{id}/history — Load Conversation
# =============================================================================


class TestSessionHistory:
    """Tests for GET /api/session/{id}/history."""

    @pytest.mark.asyncio
    async def test_load_history_success(self, mock_auth, mock_conv_store):
        """Should return conversation turns."""
        mock_conv_store.get_history.return_value = {
            "conversation_id": "conv_1",
            "title": "საუბარი დღგ-ზე",
            "turns": [
                {"role": "user", "content": "კითხვა 1"},
                {"role": "assistant", "content": "პასუხი 1"},
            ],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/session/conv_1/history")

        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == "conv_1"
        assert len(data["turns"]) == 2
        mock_conv_store.get_history.assert_awaited_once_with("conv_1", "test_user_42")

    @pytest.mark.asyncio
    async def test_load_history_not_found(self, mock_auth, mock_conv_store):
        """Should return 404 for nonexistent or other user's conversation."""
        mock_conv_store.get_history.return_value = None

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/session/not_mine/history")

        assert resp.status_code == 404


# =============================================================================
# POST /api/session/clear — Delete Conversation
# =============================================================================


class TestClearSession:
    """Tests for POST /api/session/clear."""

    @pytest.mark.asyncio
    async def test_clear_session_success(self, mock_auth, mock_conv_store):
        """Should delete the session and return cleared=true."""
        mock_conv_store.clear_session.return_value = True

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/session/clear",
                json={"conversation_id": "conv_1"},
            )

        assert resp.status_code == 200
        assert resp.json()["cleared"] is True
        mock_conv_store.clear_session.assert_awaited_once_with("conv_1", "test_user_42")

    @pytest.mark.asyncio
    async def test_clear_session_not_found(self, mock_auth, mock_conv_store):
        """Should return 404 when session doesn't exist or belongs to another user."""
        mock_conv_store.clear_session.return_value = False

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/session/clear",
                json={"conversation_id": "not_mine"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_missing_conversation_id(self, mock_auth):
        """Should return 422 when conversation_id is missing."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/session/clear", json={})

        assert resp.status_code == 422


# =============================================================================
# GET /api/health — Enhanced Health Check
# =============================================================================


class TestApiHealth:
    """Tests for GET /api/health (no auth required)."""

    @pytest.mark.asyncio
    async def test_health_db_connected(self):
        """Should return healthy status with article count when DB is connected."""
        with patch("app.api.api_router.db_manager") as mock_db:
            mock_db.ping = AsyncMock(return_value=True)
            mock_collection = AsyncMock()
            mock_collection.count_documents = AsyncMock(return_value=350)
            mock_db.db.__getitem__ = MagicMock(return_value=mock_collection)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["db_connected"] is True
        assert data["articles_count"] == 350

    @pytest.mark.asyncio
    async def test_health_db_disconnected(self):
        """Should return degraded status when DB is unreachable."""
        with patch("app.api.api_router.db_manager") as mock_db:
            mock_db.ping = AsyncMock(return_value=False)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db_connected"] is False

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self):
        """Health endpoint should NOT require API key."""
        # No auth mock — should still work
        with patch("app.api.api_router.db_manager") as mock_db:
            mock_db.ping = AsyncMock(return_value=True)
            mock_collection = AsyncMock()
            mock_collection.count_documents = AsyncMock(return_value=0)
            mock_db.db.__getitem__ = MagicMock(return_value=mock_collection)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/health")

        assert resp.status_code == 200


# =============================================================================
# SSE Helper Unit Tests
# =============================================================================


class TestSSEHelpers:
    """Unit tests for SSE formatting functions."""

    def test_sse_event_format(self):
        """_sse_event should produce valid SSE format."""
        from app.api.api_router import _sse_event

        result = _sse_event("thinking", {"step": "ვეძებ..."})
        assert result.startswith("event: thinking\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        # Verify data is valid JSON
        data_line = [l for l in result.split("\n") if l.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])
        assert parsed["step"] == "ვეძებ..."

    def test_chunk_text(self):
        """_chunk_text should split text into chunks of specified size."""
        from app.api.api_router import _chunk_text

        result = _chunk_text("a" * 200, chunk_size=80)
        assert len(result) == 3  # 80 + 80 + 40
        assert result[0] == "a" * 80
        assert result[2] == "a" * 40

    def test_chunk_text_empty(self):
        """_chunk_text with empty string should return empty list."""
        from app.api.api_router import _chunk_text

        assert _chunk_text("") == []
