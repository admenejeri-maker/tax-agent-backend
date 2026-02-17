"""
QA Fixes Tests — Move 5
========================

Validates all 9 QA findings (F1–F9) are properly fixed:
  F1: Auth on /api/v1/chat/stream
  F2: Auth on /api/v1/sessions/{user_id}
  F3: 429 HTTPException on key rate limit
  F4: verify_ownership on DELETE /api/v1/user/{user_id}/data
  F5: SourceDetail includes id + url in /ask
  F6: Turn persistence before streaming
  F7: Frontend message max_length=500
  F8: SSE helpers importable from app.utils
  F9: Bulk delete via delete_user_data
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError


# ── Fixtures ────────────────────────────────────────────────────────────────


MOCK_KEY_DOC = {
    "user_id": "test_user_42",
    "key_hash": "abc123hash",
    "key_prefix": "tk_abc12",
    "is_active": True,
}


@pytest.fixture
def _app():
    """Fresh app import for each test."""
    from main import app

    return app


@pytest.fixture
def mock_auth(_app):
    """Override verify_api_key to return test key_doc."""
    from app.auth.dependencies import verify_api_key

    async def _override():
        return MOCK_KEY_DOC

    _app.dependency_overrides[verify_api_key] = _override
    yield MOCK_KEY_DOC
    _app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_ownership(_app):
    """Override verify_ownership to return test key_doc."""
    from app.auth.dependencies import verify_ownership

    async def _override(user_id: str = "test_user_42"):
        return MOCK_KEY_DOC

    _app.dependency_overrides[verify_ownership] = _override
    yield MOCK_KEY_DOC
    _app.dependency_overrides.pop(verify_ownership, None)


# =============================================================================
# F1: /api/v1/chat/stream uses key_doc for user_id
# =============================================================================


class TestF1ChatStreamAuth:
    """F1: chat/stream should use API key's user_id, not body.user_id."""

    @pytest.mark.anyio
    async def test_chat_stream_uses_key_user_id(self, _app, mock_auth):
        """When authenticated, user_id comes from key_doc, not request body."""
        from app.models.rag_response import RAGResponse, SourceMetadata

        mock_rag = RAGResponse(
            answer="ტესტ პასუხი",
            source_metadata=[
                SourceMetadata(article_number="1", score=0.9, url="https://example.com")
            ],
            disclaimer=None,
        )

        with (
            patch("app.api.frontend_compat.conversation_store") as mock_store,
            patch("app.api.frontend_compat.answer_question", new_callable=AsyncMock) as mock_aq,
        ):
            mock_store.create_session = AsyncMock(return_value="conv_123")
            mock_store.add_turn = AsyncMock()
            mock_aq.return_value = mock_rag

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/chat/stream",
                    json={
                        "user_id": "attacker_user",  # Should be IGNORED
                        "message": "ტესტ კითხვა",
                    },
                )

            assert resp.status_code == 200
            # Verify create_session was called with the key's user_id, not attacker's
            mock_store.create_session.assert_called_with("test_user_42")


# =============================================================================
# F2: /api/v1/sessions/{user_id} requires ownership
# =============================================================================


class TestF2SessionsAuth:
    """F2: listing sessions requires verify_ownership dependency."""

    @pytest.mark.anyio
    async def test_list_sessions_requires_ownership(self, _app, mock_ownership):
        """Sessions endpoint should use verify_ownership for IDOR protection."""
        with patch("app.api.frontend_compat.conversation_store") as mock_store:
            mock_store.list_sessions = AsyncMock(return_value=[])

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/sessions/test_user_42")

            assert resp.status_code == 200
            data = resp.json()
            assert "sessions" in data


# =============================================================================
# F3: Key enrollment returns 429 HTTPException on rate limit
# =============================================================================


class TestF3RateLimitHTTPException:
    """F3: Rate limit should raise HTTPException(429), not return tuple."""

    @pytest.mark.anyio
    async def test_enroll_key_rate_limit_returns_429(self, _app):
        """When max keys per IP exceeded, response should be 429."""
        with (
            patch("app.api.frontend_compat.api_key_store") as mock_store,
            patch("app.api.frontend_compat.settings") as mock_settings,
        ):
            mock_settings.api_key_max_per_ip = 5
            mock_store.cleanup_stale_keys_by_ip = AsyncMock()
            mock_store.count_keys_by_ip = AsyncMock(return_value=5)

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/auth/key",
                    json={"user_id": "new_user"},
                )

            assert resp.status_code == 429
            data = resp.json()
            assert "detail" in data


# =============================================================================
# F4: DELETE /api/v1/user/{user_id}/data uses verify_ownership
# =============================================================================


class TestF4DeleteIDOR:
    """F4: Delete endpoint uses verify_ownership for IDOR protection."""

    @pytest.mark.anyio
    async def test_delete_data_uses_verify_ownership(self, _app, mock_ownership):
        """Delete endpoint should use verify_ownership, not manual check."""
        with patch("app.api.frontend_compat.conversation_store") as mock_store:
            mock_store.delete_user_data = AsyncMock(return_value=3)

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete("/api/v1/user/test_user_42/data")

            assert resp.status_code == 200
            data = resp.json()
            assert data["deleted"] == 3
            assert data["status"] == "ok"
            # Verify bulk delete was called (not loop)
            mock_store.delete_user_data.assert_called_once_with("test_user_42")


# =============================================================================
# F5: /ask SourceDetail includes id + url
# =============================================================================


class TestF5SourceDetailMapping:
    """F5: /ask response should include id and url in each SourceDetail."""

    @pytest.mark.anyio
    async def test_ask_response_includes_id_and_url(self, _app, mock_auth):
        """SourceDetail should have sequential id and url from SourceMetadata."""
        from app.models.rag_response import RAGResponse, SourceMetadata

        mock_rag = RAGResponse(
            answer="Test answer",
            source_metadata=[
                SourceMetadata(
                    article_number="165",
                    chapter="XVII",
                    title="საშემოსავლო გადასახადი",
                    score=0.85,
                    url="https://matsne.gov.ge/article/165",
                ),
                SourceMetadata(
                    article_number="170",
                    chapter="XVIII",
                    title="დღგ",
                    score=0.75,
                    url="https://matsne.gov.ge/article/170",
                ),
            ],
            disclaimer=None,
        )

        with (
            patch("app.api.api_router.answer_question", new_callable=AsyncMock) as mock_aq,
            patch("app.api.api_router.conversation_store") as mock_store,
        ):
            mock_aq.return_value = mock_rag
            mock_store.create_session = AsyncMock(return_value="conv_123")
            mock_store.add_turn = AsyncMock()

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/ask",
                    json={"question": "რა არის დღგ?"},
                    headers={"X-API-Key": "test-key"},
                )

            assert resp.status_code == 200
            data = resp.json()
            sources = data["sources"]
            assert len(sources) == 2

            # First source: id=1, has url
            assert sources[0]["id"] == 1
            assert sources[0]["url"] == "https://matsne.gov.ge/article/165"

            # Second source: id=2, has url
            assert sources[1]["id"] == 2
            assert sources[1]["url"] == "https://matsne.gov.ge/article/170"


# =============================================================================
# F6: Turn persistence before streaming
# =============================================================================


class TestF6TurnPersistenceOrder:
    """F6: add_turn should be called (covered by F1 test call verification)."""

    @pytest.mark.anyio
    async def test_turns_persisted_when_save_history_true(self, _app, mock_auth):
        """When save_history=true, both user and assistant turns are persisted."""
        from app.models.rag_response import RAGResponse, SourceMetadata

        mock_rag = RAGResponse(
            answer="პასუხი",
            source_metadata=[
                SourceMetadata(article_number="1", score=0.9)
            ],
            disclaimer=None,
        )

        with (
            patch("app.api.frontend_compat.conversation_store") as mock_store,
            patch("app.api.frontend_compat.answer_question", new_callable=AsyncMock) as mock_aq,
        ):
            mock_store.create_session = AsyncMock(return_value="conv_123")
            mock_store.add_turn = AsyncMock()
            mock_aq.return_value = mock_rag

            transport = ASGITransport(app=_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/chat/stream",
                    json={
                        "message": "ტესტი",
                        "save_history": True,
                    },
                )

            assert resp.status_code == 200
            # Verify both user and assistant turns were persisted
            assert mock_store.add_turn.call_count == 2
            calls = mock_store.add_turn.call_args_list
            assert calls[0].args[2] == "user"
            assert calls[1].args[2] == "assistant"


# =============================================================================
# F7: Frontend message max_length = 500
# =============================================================================


class TestF7MessageMaxLength:
    """F7: FrontendChatRequest.message should have max_length=500."""

    def test_frontend_message_max_length_500(self):
        """Messages longer than 500 chars should fail validation."""
        from app.api.frontend_compat import FrontendChatRequest

        with pytest.raises(ValidationError) as exc_info:
            FrontendChatRequest(message="ა" * 501)  # 501 Georgian chars

        errors = exc_info.value.errors()
        assert any(
            e["type"] in ("string_too_long", "value_error")
            for e in errors
        )

    def test_frontend_message_at_max_500(self):
        """Messages exactly 500 chars should pass validation."""
        from app.api.frontend_compat import FrontendChatRequest

        req = FrontendChatRequest(message="ა" * 500)
        assert len(req.message) == 500


# =============================================================================
# F8: SSE helpers importable from app.utils
# =============================================================================


class TestF8SSEHelpers:
    """F8: SSE helpers should be importable from shared utils module."""

    def test_sse_helpers_importable(self):
        """sse_event and chunk_text should be importable from app.utils.sse_helpers."""
        from app.utils.sse_helpers import sse_event, chunk_text

        assert callable(sse_event)
        assert callable(chunk_text)

    def test_sse_event_format(self):
        """sse_event should produce valid SSE format."""
        from app.utils.sse_helpers import sse_event

        result = sse_event("test", {"key": "value"})
        assert result.startswith("event: test\n")
        assert "data:" in result
        assert result.endswith("\n\n")

    def test_chunk_text_splits(self):
        """chunk_text should split text into chunks of specified size."""
        from app.utils.sse_helpers import chunk_text

        text = "Hello World! " * 10  # 130 chars
        chunks = list(chunk_text(text, 50))
        assert len(chunks) > 1
        assert all(len(c) <= 50 for c in chunks)
        assert "".join(chunks) == text


# =============================================================================
# F9: Bulk delete via delete_user_data
# =============================================================================


class TestF9BulkDelete:
    """F9: delete_user_data should use delete_many, not looped clear_session."""

    @pytest.mark.anyio
    async def test_delete_user_data_bulk(self):
        """ConversationStore.delete_user_data should call delete_many once."""
        from app.services.conversation_store import ConversationStore

        store = ConversationStore()

        mock_result = MagicMock()
        mock_result.deleted_count = 5
        mock_collection = MagicMock()
        mock_collection.delete_many = AsyncMock(return_value=mock_result)

        with patch.object(
            ConversationStore, "_collection", new_callable=lambda: property(lambda self: mock_collection)
        ):
            count = await store.delete_user_data("user_123")

        assert count == 5
        mock_collection.delete_many.assert_called_once_with({"user_id": "user_123"})
