"""
API Router — Task 7
====================

8 endpoints for the Georgian Tax AI Agent:
  POST /ask          — Synchronous RAG question
  POST /ask/stream   — SSE streaming RAG question (simulated)
  GET  /articles/{n} — Article lookup by number
  GET  /sessions     — List user conversations
  GET  /session/{id}/history — Load conversation turns
  POST /session/clear — Delete a conversation
  GET  /health       — Enhanced health check with stats

Rate limited via SlowAPI. Auth via verify_api_key dependency.
"""

from typing import Any, Dict

from app.utils.sse_helpers import sse_event as _sse_event, chunk_text as _chunk_text

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings
from app.database import db_manager
from app.auth.dependencies import verify_api_key
from app.models.api_models import (
    AskRequest,
    AskResponse,
    ArticleResponse,
    ClearRequest,
    ClearResponse,
    ErrorResponse,
    HealthResponse,
    SessionHistoryResponse,
    SessionListItem,
    SourceDetail,
)
from app.services.conversation_store import conversation_store
from app.services.rag_pipeline import answer_question

logger = structlog.get_logger(__name__)

# ─── Rate Limiter (separate instance to avoid circular import from main) ──────
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


def _extract_user_id(key_doc: dict | None) -> str:
    """Safely extract user_id from key_doc. Returns 'anonymous' when auth is disabled."""
    if key_doc is None:
        return "anonymous"
    return str(key_doc.get("user_id", key_doc.get("_id", "anonymous")))


# ─── SSE Helper (imported from app.utils.sse_helpers) ─────────────────────────


# =============================================================================
# POST /ask — Synchronous RAG
# =============================================================================


@router.post("/ask", response_model=AskResponse)
@limiter.limit(f"{settings.rate_limit}/minute")
async def ask_question(
    request: Request,
    body: AskRequest,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """Ask a question about Georgian tax law."""
    user_id = _extract_user_id(key_doc)

    # ── Create or resume session ──────────────────────────────────────
    conversation_id = body.conversation_id
    history = None

    if conversation_id:
        session = await conversation_store.get_history(conversation_id, user_id)
        if not session:
            raise HTTPException(status_code=404, detail="Conversation not found")
        # Build history for RAG pipeline
        history = [
            {"role": t["role"], "text": t["content"]}
            for t in session.get("turns", [])
        ]
    else:
        conversation_id = await conversation_store.create_session(user_id)

    # ── Run RAG pipeline ──────────────────────────────────────────────
    rag_response = await answer_question(body.question, history=history)

    if rag_response.error:
        raise HTTPException(status_code=500, detail=rag_response.error)

    # ── Save turns ────────────────────────────────────────────────────
    await conversation_store.add_turn(conversation_id, user_id, "user", body.question)
    await conversation_store.add_turn(conversation_id, user_id, "assistant", rag_response.answer)

    # ── Map RAGResponse → AskResponse ─────────────────────────────────
    return AskResponse(
        answer=rag_response.answer,
        sources=[
            SourceDetail(
                id=i + 1,
                article_number=s.article_number,
                chapter=s.chapter,
                title=s.title,
                score=s.score,
                url=s.url,
                text=s.text,
            )
            for i, s in enumerate(rag_response.source_metadata)
        ],
        disclaimer=rag_response.disclaimer,
        temporal_warning=rag_response.temporal_warning,
        confidence_score=rag_response.confidence_score,
        conversation_id=conversation_id,
    )


# =============================================================================
# POST /ask/stream — SSE Streaming RAG (Simulated)
# =============================================================================


@router.post("/ask/stream")
@limiter.limit(f"{settings.rate_limit}/minute")
async def ask_stream(
    request: Request,
    body: AskRequest,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """Stream a RAG answer via Server-Sent Events (simulated chunking)."""
    user_id = _extract_user_id(key_doc)

    async def generate():
        try:
            # ── Session handling ──────────────────────────────────────
            conversation_id = body.conversation_id
            history = None

            if conversation_id:
                session = await conversation_store.get_history(conversation_id, user_id)
                if not session:
                    yield _sse_event("error", {"error": "Conversation not found", "code": "NOT_FOUND"})
                    return
                history = [
                    {"role": t["role"], "text": t["content"]}
                    for t in session.get("turns", [])
                ]
            else:
                conversation_id = await conversation_store.create_session(user_id)

            # ── Thinking phase ────────────────────────────────────────
            yield _sse_event("thinking", {"step": "საგადასახადო კოდექსში ვეძებ..."})

            # ── Run RAG ───────────────────────────────────────────────
            rag_response = await answer_question(body.question, history=history)

            if rag_response.error:
                yield _sse_event("error", {"error": rag_response.error, "code": "LLM_ERROR"})
                return

            # ── Sources ───────────────────────────────────────────────
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
            yield _sse_event("sources", sources_data)

            # ── Disclaimer (if applicable) ────────────────────────────
            if rag_response.disclaimer:
                yield _sse_event("disclaimer", {
                    "text": rag_response.disclaimer,
                    "temporal_warning": rag_response.temporal_warning,
                })

            # ── Stream text in chunks ─────────────────────────────────
            for chunk in _chunk_text(rag_response.answer, 80):
                yield _sse_event("text", {"content": chunk})

            # ── Save turns ────────────────────────────────────────────
            await conversation_store.add_turn(conversation_id, user_id, "user", body.question)
            await conversation_store.add_turn(conversation_id, user_id, "assistant", rag_response.answer)

            # ── Quick replies (follow-up suggestions) ──────────────
            if rag_response.follow_up_suggestions:
                yield _sse_event("quick_replies", {"options": rag_response.follow_up_suggestions})

            # ── Done ──────────────────────────────────────────────
            yield _sse_event("done", {
                "conversation_id": conversation_id,
                "confidence_score": rag_response.confidence_score,
            })

        except Exception as e:
            logger.error("sse_stream_error", error=str(e))
            yield _sse_event("error", {"error": str(e), "code": "STREAM_ERROR"})

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
# GET /articles/{number} — Article Lookup
# =============================================================================


@router.get("/articles/{number}", response_model=ArticleResponse)
@limiter.limit(f"{settings.rate_limit}/minute")
async def get_article(
    request: Request,
    number: int,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """Look up a Georgian Tax Code article by number."""
    if not (1 <= number <= 500):
        raise HTTPException(
            status_code=422,
            detail="Article number must be between 1 and 500",
        )

    article = await db_manager.db["tax_articles"].find_one(
        {"article_number": number},
        {"_id": 0},
    )

    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    return ArticleResponse(**article)


# =============================================================================
# GET /sessions — List User Conversations
# =============================================================================


@router.get("/sessions", response_model=list[SessionListItem])
@limiter.limit(f"{settings.rate_limit}/minute")
async def list_sessions(
    request: Request,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """List the current user's conversation sessions."""
    user_id = _extract_user_id(key_doc)
    sessions = await conversation_store.list_sessions(user_id)
    return [SessionListItem(**s) for s in sessions]


# =============================================================================
# GET /session/{id}/history — Load Conversation Turns
# =============================================================================


@router.get("/session/{conversation_id}/history", response_model=SessionHistoryResponse)
@limiter.limit(f"{settings.rate_limit}/minute")
async def get_session_history(
    request: Request,
    conversation_id: str,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """Load conversation history for a specific session."""
    user_id = _extract_user_id(key_doc)
    session = await conversation_store.get_history(conversation_id, user_id)

    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return SessionHistoryResponse(
        conversation_id=session["conversation_id"],
        title=session.get("title", "ახალი საუბარი"),
        turns=session.get("turns", []),
    )


# =============================================================================
# POST /session/clear — Delete Conversation
# =============================================================================


@router.post("/session/clear", response_model=ClearResponse)
@limiter.limit(f"{settings.rate_limit}/minute")
async def clear_session(
    request: Request,
    body: ClearRequest,
    key_doc: Dict[str, Any] = Depends(verify_api_key),
):
    """Delete a conversation session."""
    user_id = _extract_user_id(key_doc)
    deleted = await conversation_store.clear_session(body.conversation_id, user_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ClearResponse(cleared=True)


# =============================================================================
# GET /health — Enhanced Health Check
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def api_health(request: Request):
    """Enhanced health endpoint with article count (no auth required)."""
    db_ok = False
    articles_count = 0

    try:
        db_ok = await db_manager.ping()
        if db_ok:
            articles_count = await db_manager.db["tax_articles"].count_documents({})
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        db_connected=db_ok,
        articles_count=articles_count,
    )
