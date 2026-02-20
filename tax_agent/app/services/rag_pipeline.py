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
from app.services.vector_search import (
    hybrid_search,
    enrich_with_cross_refs,
    rerank_with_exceptions,
)
from app.services.router import route_query
from app.services.logic_loader import get_logic_rules
from app.services.critic import critique_answer
from app.services.follow_up_generator import generate_follow_ups
from app.services.safety import (
    build_generation_config,
    check_safety_block,
    SAFETY_FALLBACK_MESSAGE,
)

logger = structlog.get_logger(__name__)

# Georgian disclaimer when critic rejects and regen is disabled/fails
DISCLAIMER_CRITIC = "პასუხი შეიძლება არ იყოს სრულად ზუსტი."


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


MAX_SOURCE_TEXT_LEN = 2000


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
        body = r.get("body", "")
        truncated = (
            body[:MAX_SOURCE_TEXT_LEN] + "…"
            if len(body) > MAX_SOURCE_TEXT_LEN
            else body
        )
        metadata.append(SourceMetadata(
            article_number=r.get("article_number"),
            chapter=r.get("kari"),
            title=r.get("title"),
            score=r.get("score", 0.0),
            url=url,
            text=truncated or None,
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


def pack_context(results: List[dict], budget: int) -> List[dict]:
    """Pack search results by RRF relevance order until budget exhausted.

    Replaces the old crude slicing (search_results[:search_limit]) with
    budget-aware packing that respects reranked order and uses partial
    truncation for the last fitting result.

    Args:
        results: Search results already sorted by rerank_with_exceptions.
        budget: Maximum total characters for all body fields combined.

    Returns:
        Packed results list, each with body ≤ remaining budget.
    """
    if not results or budget <= 0:
        return []

    packed = []
    remaining = budget
    for r in results:
        body = r.get("body", "")
        body_len = len(body)
        if body_len <= remaining:
            packed.append(r)
            remaining -= body_len
        elif remaining > 200:
            # Partial truncation: include truncated body with marker
            truncated_body = body[:remaining - len("\n[...]")] + "\n[...]"
            packed.append({**r, "body": truncated_body})
            break
        else:
            break

    if len(packed) < len(results):
        logger.info(
            "context_packed",
            kept=len(packed),
            dropped=len(results) - len(packed),
            budget=budget,
        )
    return packed


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
        search_results = await hybrid_search(search_query, domain=domain)

        # ── Step 2.1: Cross-ref graph expansion (gated) ─────
        if settings.graph_expansion_enabled:
            _pre_enrich_count = len(search_results)
            search_results = await enrich_with_cross_refs(
                search_results,
                max_refs=settings.max_graph_refs,
            )
            search_results = rerank_with_exceptions(search_results)
            logger.info(
                "graph_expansion",
                primary=_pre_enrich_count,
                total=len(search_results),
                added=len(search_results) - _pre_enrich_count,
            )

        # ── Step 2.2: Context budget guard ─────────────────
        search_results = pack_context(search_results, settings.max_context_chars)

        context_chunks = [
            r.get("body", "")
            for r in search_results
            if r.get("body")
        ]

        # ── Step 2.5: Pre-compute source metadata + citation refs ─
        # ── A10 fix: exclude cross-refs from user-facing citations ──
        source_metadata = _extract_source_metadata(
            [r for r in search_results if not r.get("is_cross_ref")]
        )

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
            domain=domain,
            logic_rules=logic_rules,
        )

        # 🔍 DEBUG: Log system prompt key markers
        logger.info(
            "system_prompt_built",
            prompt_len=len(system_prompt),
            has_emoji_sources="📚 წყაროები" in system_prompt,
            has_markdown_rule="Markdown" in system_prompt,
            has_citations=source_refs is not None,
            preview=system_prompt[:500],
        )

        # ── Step 4: Gemini generation ─────────────────────────────
        client = get_genai_client()
        contents = _build_contents(
            query,
            history=history,
            max_turns=settings.max_history_turns,
        )

        # 3-attempt safety fallback: primary → relaxed → backup model
        attempts = [
            (settings.generation_model, "primary"),
            (settings.generation_model, "fallback"),
            (settings.safety_fallback_model, "primary"),
        ]

        answer_text = SAFETY_FALLBACK_MESSAGE
        safety_fallback = False

        for attempt_num, (model, safety_level) in enumerate(attempts, 1):
            if attempt_num > 1 and not settings.safety_retry_enabled:
                break
            try:
                gen_config = build_generation_config(
                    system_prompt, settings.temperature,
                    settings.max_output_tokens, safety_level=safety_level,
                )
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=gen_config,
                )
                is_blocked, block_reason, text = check_safety_block(response)
            except Exception as e:
                logger.warning(
                    "safety_attempt_exception",
                    attempt=attempt_num, model=model, error=str(e),
                )
                continue

            if not is_blocked:
                answer_text = text
                safety_fallback = attempt_num > 1
                logger.info(
                    "generation_success",
                    attempt=attempt_num, model=model,
                    finish_reason=block_reason,
                    answer_len=len(text),
                    answer_preview=text[:300],
                    has_emoji_footer="📚 წყაროები" in text,
                )
                if safety_fallback:
                    logger.info(
                        "safety_retry_succeeded",
                        attempt=attempt_num, model=model,
                    )
                break

            logger.warning(
                "safety_block_detected",
                attempt=attempt_num, model=model, reason=block_reason,
            )
        else:
            logger.error("all_safety_attempts_failed")

        # ── Step 4.5: Critic QA review (gated) ──────────────────
        # ── B1 fix: exclude cross-refs (score=0.0) from confidence ──
        confidence = _calculate_confidence(
            [r for r in search_results if not r.get("is_cross_ref")]
        )
        if settings.critic_enabled and source_refs:
            critic_result = await critique_answer(
                answer=answer_text,
                source_refs=source_refs,
                confidence=confidence,
            )
            if not critic_result.approved and critic_result.feedback:
                if settings.critic_regeneration_enabled:
                    # Single retry: inject feedback into system prompt
                    regen_instruction = (
                        f"\n\n<CRITIC_FEEDBACK>\n{critic_result.feedback}\n</CRITIC_FEEDBACK>"
                        "\nFix the issues above and regenerate your answer."
                    )
                    regen_config = build_generation_config(
                        system_prompt + regen_instruction,
                        settings.temperature,
                        settings.max_output_tokens,
                        safety_level="primary",
                    )
                    regen_response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=settings.generation_model,
                        contents=contents,
                        config=regen_config,
                    )
                    regen_text = (
                        regen_response.text
                        if hasattr(regen_response, "text")
                        else str(regen_response)
                    )
                    regen_critic = await critique_answer(
                        answer=regen_text,
                        source_refs=source_refs,
                        confidence=confidence,
                    )
                    if regen_critic.approved:
                        answer_text = regen_text
                        logger.info("critic_regen_accepted")
                    else:
                        answer_text += f"\n\n{DISCLAIMER_CRITIC}"
                        logger.warning("critic_regen_also_rejected")
                else:
                    answer_text += f"\n\n{DISCLAIMER_CRITIC}"
                    logger.warning(
                        "critic_rejected_no_regen",
                        feedback=critic_result.feedback,
                    )
        elif settings.critic_enabled and not source_refs:
            logger.debug("critic_skipped_no_sources")

        # ── Step 4.6: Follow-up suggestions (gated) ─────────────
        follow_ups = []
        if settings.follow_up_enabled and not is_red_zone and answer_text != SAFETY_FALLBACK_MESSAGE:
            follow_ups = await generate_follow_ups(
                answer=answer_text,
                query=query,
                domain=domain,
            )

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
            safety_fallback=safety_fallback,
            follow_up_suggestions=follow_ups,
        )

    except Exception as e:
        logger.error("rag_pipeline_failed", error=str(e), query=_sanitize_for_log(query))
        return RAGResponse(
            answer="",
            error=f"RAG pipeline error: {str(e)}",
        )
