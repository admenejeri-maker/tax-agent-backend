"""
Frontend Compatibility Router
==============================

Translates between the Scoop frontend's protocol and the Tax Agent's RAG pipeline.

The Scoop frontend expects:
  POST /api/v1/auth/key              — API key enrollment
  POST /api/v1/chat/stream           — SSE with {user_id, message, session_id}
  GET  /api/v1/sessions/{user_id}    — List conversations
  GET  /api/v1/session/{id}/history  — Load conversation turns
  DELETE /api/v1/user/{user_id}/data — Delete user data

The Tax Agent's internal protocol uses different paths and field names.
This router bridges the gap without modifying either system.
"""

from typing import Any, Optional

from app.utils.sse_helpers import sse_event as _sse, chunk_text as _chunk_text

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.api_key_store import api_key_store
from app.auth.dependencies import verify_api_key, verify_ownership
from app.auth.key_generator import KeyGenerator
from app.services.conversation_store import conversation_store
from app.services.rag_pipeline import answer_question
from config import settings

logger = structlog.get_logger(__name__)

# =============================================================================
# Router — No prefix; routes include /api/v1/... explicitly
# =============================================================================

compat_router = APIRouter(tags=["frontend-compat"])


# =============================================================================
# Request/Response Models (Frontend Protocol)
# =============================================================================


class FrontendChatRequest(BaseModel):
    """Request body matching the Scoop frontend's sendMessage shape."""

    user_id: str = Field(default="anonymous", description="Frontend user ID")
    message: str = Field(..., min_length=1, max_length=500, description="User question")
    session_id: Optional[str] = Field(None, description="Resume existing conversation")
    save_history: bool = Field(default=True, description="Whether to persist turns")


class FrontendKeyRequest(BaseModel):
    """Request body matching the Scoop frontend's enrollApiKey shape."""

    user_id: str = Field(..., min_length=1, max_length=128, description="User ID")


# ─── SSE Helpers (imported from app.utils.sse_helpers) ────────────────────────


# =============================================================================
# POST /api/v1/auth/key — API Key Enrollment (Frontend Protocol)
# =============================================================================


@compat_router.post("/api/v1/auth/key")
async def frontend_enroll_key(body: FrontendKeyRequest, request: Request):
    """
    API key enrollment endpoint matching the frontend's expected path.

    Frontend calls:  POST /api/v1/auth/key  with {user_id}
    Tax Agent has:   POST /auth/key          (different prefix)

    This proxies to the existing auth system.
    """
    ip_address = request.client.host if request.client else "unknown"

    # Clean up stale keys before rate limiting
    await api_key_store.cleanup_stale_keys_by_ip(ip_address)

    # IP-based rate limit
    ip_key_count = await api_key_store.count_keys_by_ip(ip_address)
    if ip_key_count >= settings.api_key_max_per_ip:
        logger.warning("frontend_key_rate_limit", ip_prefix=ip_address[:8])
        raise HTTPException(status_code=429, detail="Too many API keys from this IP")

    # Generate and store the key
    generated = await api_key_store.create_key(
        user_id=body.user_id,
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
        origin=request.headers.get("origin"),
    )

    return {
        "key": generated.raw_key,
        "user_id": generated.user_id,
        "key_prefix": generated.key_prefix,
    }


# =============================================================================
# POST /api/v1/chat/stream — SSE Streaming (Frontend Protocol)
# =============================================================================


@compat_router.post("/api/v1/chat/stream")
async def frontend_chat_stream(
    request: Request,
    body: FrontendChatRequest,
    key_doc: Optional[dict] = Depends(verify_api_key),
):
    """
    SSE endpoint that speaks the Scoop frontend's protocol.

    Maps:
      body.message      → question  (for RAG pipeline)
      body.session_id   → conversation_id  (for conversation store)

    Emits SSE events that the frontend's useSSEStream hook can parse:
      thinking  → {content: "..."}
      text      → {content: "..."}
      done      → {session_id: "..."}
      error     → {message: "..."}
    """
    # Trust API key for user_id; fall back to body only when auth is optional
    if key_doc:
        user_id = str(key_doc.get("user_id", "anonymous"))
    else:
        user_id = body.user_id or "anonymous"

    async def generate():
        try:
            # ── Session handling (map session_id → conversation_id) ────────
            conversation_id = body.session_id
            history = None

            if conversation_id:
                session = await conversation_store.get_history(conversation_id, user_id)
                if not session:
                    # Stale/unknown session_id — start a fresh conversation instead
                    logger.warning(
                        "frontend_stale_session",
                        session_id=conversation_id[:12],
                        user_id=user_id[:8],
                    )
                    conversation_id = None  # will create new below
                else:
                    history = [
                        {"role": t["role"], "text": t["content"]}
                        for t in session.get("turns", [])
                    ]

            if not conversation_id:
                conversation_id = await conversation_store.create_session(user_id)

            # ── Thinking phase ────────────────────────────────────────────
            yield _sse("thinking", {"content": "საგადასახადო კოდექსში ვეძებ..."})

            # ── Run RAG pipeline ──────────────────────────────────────────
            rag_response = await answer_question(body.message, history=history)

            if rag_response.error:
                yield _sse("error", {"message": rag_response.error, "code": "LLM_ERROR"})
                return

            # ── Persist turns BEFORE streaming (prevent data loss) ─────
            if body.save_history:
                await conversation_store.add_turn(
                    conversation_id, user_id, "user", body.message
                )
                # Serialize sources for MongoDB persistence
                sources_for_db = None
                if rag_response.source_metadata:
                    sources_for_db = [
                        {
                            "id": i + 1,
                            "article_number": s.article_number,
                            "chapter": s.chapter,
                            "title": s.title,
                            "score": s.score,
                            "url": s.url,
                            "text": s.text,
                        }
                        for i, s in enumerate(rag_response.source_metadata)
                    ]
                await conversation_store.add_turn(
                    conversation_id, user_id, "assistant", rag_response.answer,
                    sources=sources_for_db,
                )

            # ── Stream text in chunks ─────────────────────────────────────
            for chunk in _chunk_text(rag_response.answer, 80):
                yield _sse("text", {"content": chunk})

            # ── Sources event for citation sidebar (Task 7) ────────────
            if rag_response.source_metadata:
                sources_data = [
                    {
                        "id": i + 1,
                        "article_number": s.article_number,
                        "chapter": s.chapter,
                        "title": s.title,
                        "score": s.score,
                        "url": s.url,
                        "text": s.text,
                    }
                    for i, s in enumerate(rag_response.source_metadata)
                ]
                yield _sse("sources", sources_data)

            # ── Disclaimer as text event ──────────────────────────────────
            if rag_response.disclaimer:
                disclaimer_text = f"\n\n⚠️ *{rag_response.disclaimer}*"
                if rag_response.temporal_warning:
                    disclaimer_text += f"\n⏰ *{rag_response.temporal_warning}*"
                yield _sse("text", {"content": disclaimer_text})

            # ── Done — Frontend expects {session_id: "..."} ──────────────
            yield _sse("done", {"session_id": conversation_id})

        except Exception as e:
            logger.error("frontend_compat_stream_error", error=str(e))
            yield _sse("error", {"message": str(e), "code": "STREAM_ERROR"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# GET /api/v1/sessions/{user_id} — List Conversations (Frontend Protocol)
# =============================================================================


@compat_router.get("/api/v1/sessions/{user_id}")
async def frontend_list_sessions(
    user_id: str,
    key_doc: Optional[dict] = Depends(verify_ownership),
):
    """
    List conversations for a user.

    Frontend expects: { sessions: [{ session_id, title, created_at?, updated_at? }] }
    Tax Agent returns: [{ conversation_id, title, created_at, updated_at, turn_count }]
    """
    sessions = await conversation_store.list_sessions(user_id)
    return {
        "sessions": [
            {
                "session_id": s["conversation_id"],
                "title": s.get("title", "ახალი საუბარი"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
            }
            for s in sessions
        ]
    }


# =============================================================================
# GET /api/v1/session/{session_id}/history — Load Conversation Turns
# =============================================================================


@compat_router.get("/api/v1/session/{session_id}/history")
async def frontend_load_history(
    session_id: str,
    request: Request,
    key_doc: Optional[dict] = Depends(verify_api_key),
):
    """
    Load conversation history for a specific session.

    Frontend expects: { messages: [{ role, content }] }

    user_id resolved from API key (via verify_api_key dependency)
    since the frontend's apiFetch sends X-API-Key but no user_id param.
    """
    # Resolve user_id from API key or fallback
    user_id = "anonymous"
    if key_doc:
        user_id = str(key_doc.get("user_id", "anonymous"))

    session = await conversation_store.get_history(session_id, user_id)
    if not session:
        return {"messages": []}

    return {
        "messages": [
            {
                "role": t["role"],
                "content": t["content"],
                **({"sources": t["sources"]} if t.get("sources") else {}),
            }
            for t in session.get("turns", [])
        ]
    }


# =============================================================================
# DELETE /api/v1/user/{user_id}/data — Delete User Data (Frontend Protocol)
# =============================================================================


@compat_router.delete("/api/v1/user/{user_id}/data")
async def frontend_delete_user_data(
    user_id: str,
    key_doc: Optional[dict] = Depends(verify_ownership),
):
    """
    Delete all data for a user.

    Frontend calls: DELETE /api/v1/user/{userId}/data
    This removes all conversation sessions owned by the user.
    IDOR protection handled by verify_ownership dependency.
    """
    deleted_count = await conversation_store.delete_user_data(user_id)

    logger.info("frontend_user_data_deleted", user_id=user_id[:8], count=deleted_count)
    return {"deleted": deleted_count, "status": "ok"}
