"""
RAG Pipeline Orchestrator — Task 4/6c/6d
========================================

Core `answer_question()` function that orchestrates the full RAG flow:
  1. Run pre-retrieval classifiers
  2. Execute hybrid search
  3. Build system prompt with context
  4. Call Gemini generation (via asyncio.to_thread)
  5. Package into RAGResponse with metadata

Stateless: accepts `history` as a parameter (no session state stored).
"""

import asyncio
import re
from typing import List, Optional

import structlog

from config import settings
from app.models.rag_response import RAGResponse, SourceMetadata
from app.services.classifiers import (
    classify_red_zone,
    resolve_terms,
    detect_past_date,
)
from app.services.tax_system_prompt import (
    build_system_prompt,
    DISCLAIMER_CALCULATION,
    DISCLAIMER_TEMPORAL,
)
from app.services.embedding_service import get_genai_client
from app.services.query_rewriter import rewrite_query
from app.services.vector_search import hybrid_search
from app.services.router import route_query
from app.services.logic_loader import get_logic_rules
from app.services.critic import critique_answer

logger = structlog.get_logger(__name__)


def _sanitize_for_log(text: str, max_len: int = 50) -> str:
    """Strip potential PII (digit sequences 5+) from log text."""
    return re.sub(r'\d{5,}', '[REDACTED]', text)[:max_len]


def _build_contents(
    query: str,
    history: Optional[List[dict]] = None,
    max_turns: int = 5,
) -> list:
    """Build the Gemini `contents` array from history + current query.

    Args:
        query: Current user question.
        history: Past conversation turns as [{"role": "user"|"model", "text": "..."}].
        max_turns: Maximum number of past turns to include.

    Returns:
        List of content dicts for the Gemini API.
    """
    contents = []
    if history:
        for turn in history[-max_turns:]:
            contents.append({
                "role": turn.get("role", "user"),
                "parts": [{"text": turn.get("text", "")}],
            })
    contents.append({
        "role": "user",
        "parts": [{"text": query}],
    })
    return contents


def _extract_source_metadata(results: List[dict]) -> List[SourceMetadata]:
    """Extract SourceMetadata from hybrid search results.

    Args:
        results: Raw search result dicts.

    Returns:
        List of SourceMetadata objects with Matsne deep-link URLs.
    """
    metadata = []
    for r in results:
        art_num = r.get("article_number")
        url = (
            f"{settings.matsne_base_url}#Article_{art_num}"
            if art_num else None
        )
        metadata.append(SourceMetadata(
            article_number=r.get("article_number"),
            chapter=r.get("kari"),
            title=r.get("title"),
            score=r.get("score", 0.0),
            url=url,
        ))
    return metadata


def _calculate_confidence(results: List[dict]) -> float:
    """Calculate a confidence score from search results.

    Uses the average score of the top results, clamped to [0, 1].

    Args:
        results: Raw search result dicts with 'score' field.

    Returns:
        Float between 0.0 and 1.0.
    """
    if not results:
        return 0.0
    scores = [r.get("score", 0.0) for r in results]
    avg = sum(scores) / len(scores)
    return min(max(avg, 0.0), 1.0)


async def answer_question(
    query: str,
    *,
    history: Optional[List[dict]] = None,
) -> RAGResponse:
    """Orchestrate the full RAG pipeline for a Georgian tax question.

    Steps:
      1. Run classifiers (red zone, term resolver, past-date)
      2. Execute hybrid search
      3. Build system prompt with context
      4. Call Gemini generation (sync call wrapped in asyncio.to_thread)
      5. Assemble RAGResponse

    Args:
        query: User's tax question in Georgian.
        history: Optional conversation history for multi-turn context.

    Returns:
        RAGResponse with answer, sources, metadata, and any disclaimers.
        On error, returns RAGResponse with error field set.
    """
    try:
        # ── Step 1: Pre-retrieval classifiers ─────────────────────
        is_red_zone = classify_red_zone(query)
        definitions = await resolve_terms(query)
        temporal_flag, temporal_year = detect_past_date(query)

        # ── Step 1.3: Domain routing (gated) ─────────────────────
        domain = "GENERAL"
        if settings.router_enabled:
            route_result = await route_query(query)
            domain = route_result.domain
            logger.info(
                "router_result",
                domain=domain,
                confidence=route_result.confidence,
                method=route_result.method,
            )

        # ── Step 1.4: Logic rules (gated via loader) ─────────────
        logic_rules = get_logic_rules(domain)

        # ── Step 1.5: Query rewriting for search (Task 4) ────────
        search_query = query
        if history and len(history) > 1:
            search_query = await rewrite_query(query, history)

        # ── Step 2: Hybrid search ─────────────────────────────────
        search_results = await hybrid_search(search_query)

        context_chunks = [
            r.get("body", "")
            for r in search_results
            if r.get("body")
        ]

        # ── Step 2.5: Pre-compute source metadata + citation refs ─
        source_metadata = _extract_source_metadata(search_results)

        source_refs = None
        if settings.citation_enabled and source_metadata:
            source_refs = [
                {"id": i + 1, "article_number": s.article_number, "title": s.title}
                for i, s in enumerate(source_metadata)
            ]

        # ── Step 3: Build system prompt ───────────────────────────
        system_prompt = build_system_prompt(
            context_chunks=context_chunks,
            definitions=definitions,
            source_refs=source_refs,
            is_red_zone=is_red_zone,
            temporal_year=temporal_year,
            logic_rules=logic_rules,
        )

        # ── Step 4: Gemini generation ─────────────────────────────
        client = get_genai_client()
        contents = _build_contents(
            query,
            history=history,
            max_turns=settings.max_history_turns,
        )

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.generation_model,
            contents=contents,
            config={
                "system_instruction": system_prompt,
                "temperature": settings.temperature,
                "max_output_tokens": settings.max_output_tokens,
            },
        )

        answer_text = response.text if hasattr(response, "text") else str(response)

        # ── Step 4.5: Critic QA review (gated) ──────────────────
        confidence = _calculate_confidence(search_results)
        if settings.critic_enabled:
            if not source_refs:
                logger.debug("critic_skipped_no_sources")
            else:
                critic_result = await critique_answer(
                    answer=answer_text,
                    source_refs=source_refs,
                    confidence=confidence,
                )
                if not critic_result.approved and critic_result.feedback:
                    logger.warning(
                        "critic_rejected",
                        feedback=critic_result.feedback,
                    )
                    answer_text += f"\n\n⚠️ {critic_result.feedback}"

        # ── Step 5: Assemble response ─────────────────────────────
        source_refs_list = [
            str(r.get("article_number", "unknown"))
            for r in search_results
            if r.get("article_number")
        ]

        disclaimer = DISCLAIMER_CALCULATION if is_red_zone else None
        temporal_warning = (
            DISCLAIMER_TEMPORAL.format(year=temporal_year)
            if temporal_flag and temporal_year
            else None
        )

        return RAGResponse(
            answer=answer_text,
            sources=source_refs_list,
            source_metadata=source_metadata,
            confidence_score=confidence,
            disclaimer=disclaimer,
            temporal_warning=temporal_warning,
        )

    except Exception as e:
        logger.error("rag_pipeline_failed", error=str(e), query=_sanitize_for_log(query))
        return RAGResponse(
            answer="",
            error=f"RAG pipeline error: {str(e)}",
        )
