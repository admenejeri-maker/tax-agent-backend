"""
Contextual Query Rewriter — Task 4
====================================

Rewrites ambiguous follow-up queries into standalone queries using
conversation history context. Used BEFORE vector search to improve
retrieval quality in multi-turn conversations.

Fail-safe: returns original query on any error (timeout, API failure, etc.)
"""

import asyncio
from typing import List, Optional

import structlog

from config import settings
from app.services.embedding_service import get_genai_client
from app.services.safety import build_generation_config

logger = structlog.get_logger(__name__)

REWRITE_PROMPT = """\
მომხმარებლის ახალი შეკითხვა შეიძლება ეყრდნობოდეს წინა დიალოგს.
გადააკეთე ეს შეკითხვა დამოუკიდებელ, სრულ კითხვად რომელიც \
საძიებო სისტემას გაუგებს კონტექსტის გარეშე.

მხოლოდ გადაწერილი შეკითხვა დააბრუნე, სხვა არაფერი.

დიალოგის ისტორია:
{history}

ახალი შეკითხვა: {query}

დამოუკიდებელი შეკითხვა:"""


def _format_history(history: List[dict], max_turns: int = 4) -> str:
    """Format conversation history into a readable string for the prompt.

    Args:
        history: List of turn dicts with 'role' and 'text' keys.
        max_turns: Maximum number of recent turns to include.

    Returns:
        Multi-line string with Georgian role labels.
    """
    lines = []
    for turn in history[-max_turns:]:
        role = "მომხმარებელი" if turn.get("role") == "user" else "ასისტენტი"
        text = turn.get("text", "")
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


async def rewrite_query(
    query: str,
    history: Optional[List[dict]] = None,
) -> str:
    """Rewrite a follow-up query as standalone using conversation context.

    Returns original query if:
    - No history provided or empty
    - Only 1 turn in history (first question, nothing to rewrite against)
    - Rewriter times out (configurable, default 3s)
    - Any error occurs (fail-safe: never block the pipeline)

    Args:
        query: The user's current question.
        history: Past turns as [{"role": "user"|"model", "text": "..."}].

    Returns:
        Rewritten standalone query, or original query on fallback.
    """
    # Guard: nothing to rewrite against
    if not history or len(history) < 2:
        return query

    try:
        client = get_genai_client()
        prompt = REWRITE_PROMPT.format(
            history=_format_history(history),
            query=query,
        )

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=settings.query_rewrite_model,
                contents=prompt,
                config=build_generation_config(
                    system_prompt="",
                    temperature=0.1,
                    max_output_tokens=256,
                    safety_level="primary",
                ),
            ),
            timeout=settings.query_rewrite_timeout,
        )

        rewritten = response.text.strip() if hasattr(response, "text") else ""

        if not rewritten:
            logger.warning("rewriter_empty_response", original=query[:50])
            return query

        logger.info(
            "query_rewritten",
            original=query[:50],
            rewritten=rewritten[:50],
        )
        return rewritten

    except asyncio.TimeoutError:
        logger.warning("rewriter_timeout", query=query[:50])
        return query
    except Exception as e:
        logger.error("rewriter_failed", error=str(e), query=query[:50])
        return query
