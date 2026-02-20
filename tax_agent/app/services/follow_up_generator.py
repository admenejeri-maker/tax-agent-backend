"""
Follow-Up Suggestions Generator — Phase 1: Quick Replies
==========================================================

Generates context-aware follow-up question suggestions after each RAG
response. Uses a lightweight Gemini Flash call to produce 3-4 related
tax questions in Georgian.

Fail-safe: returns empty list on any error (timeout, API failure, etc.)
Never blocks the main pipeline.
"""

import asyncio
import json
from typing import List

import structlog

from config import settings
from app.services.embedding_service import get_genai_client
from app.services.safety import build_generation_config

logger = structlog.get_logger(__name__)

FOLLOW_UP_PROMPT = """\
მომხმარებელმა დასვა საგადასახადო კითხვა და მიიღო პასუხი.
შექმენი {max_suggestions} სავარაუდო შემდეგი კითხვა, რომელიც მომხმარებელს \
შეიძლება დაეხმაროს თემის გაღრმავებაში.

წესები:
- მხოლოდ ქართულად
- ყოველი კითხვა უნდა იყოს მოკლე (15 სიტყვამდე)
- კითხვები უნდა იყოს კონკრეტული და საგადასახადო თემაზე
- არ გაიმეორო ორიგინალი კითხვა
- დააბრუნე მხოლოდ JSON მასივი, სხვა არაფერი

ფორმატი:
[{{"title": "კითხვის მოკლე ტექსტი", "payload": "კითხვის სრული ტექსტი"}}]

ორიგინალი კითხვა: {query}

პასუხი: {answer_preview}

JSON მასივი:"""


async def generate_follow_ups(
    answer: str,
    query: str,
    domain: str = "GENERAL",
) -> List[dict]:
    """Generate follow-up question suggestions from a RAG answer.

    Returns 3-4 follow-up questions as [{title, payload}] dicts.
    Fail-safe: returns empty list on any error.

    Args:
        answer: The RAG pipeline answer text.
        query: The user's original question.
        domain: Tax domain (GENERAL, VAT, INCOME_TAX, etc.)

    Returns:
        List of dicts with 'title' and 'payload' keys, or empty list.
    """
    if not settings.follow_up_enabled:
        return []

    # Don't generate follow-ups for very short or error answers
    if not answer or len(answer) < 50:
        return []

    try:
        client = get_genai_client()

        # Use truncated answer to save tokens (first 500 chars is enough context)
        answer_preview = answer[:500] + "..." if len(answer) > 500 else answer

        prompt = FOLLOW_UP_PROMPT.format(
            max_suggestions=settings.follow_up_max_suggestions,
            query=query,
            answer_preview=answer_preview,
        )

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=settings.follow_up_model,
                contents=prompt,
                config=build_generation_config(
                    system_prompt="",
                    temperature=0.7,
                    max_output_tokens=512,
                    safety_level="primary",
                ),
            ),
            timeout=settings.follow_up_timeout,
        )

        raw_text = response.text.strip() if hasattr(response, "text") else ""

        if not raw_text:
            logger.warning("follow_up_empty_response")
            return []

        # Parse JSON array from response
        suggestions = _parse_suggestions(raw_text)

        logger.info(
            "follow_ups_generated",
            count=len(suggestions),
            query_preview=query[:50],
        )
        return suggestions

    except asyncio.TimeoutError:
        logger.warning("follow_up_timeout", query=query[:50])
        return []
    except Exception as e:
        logger.error("follow_up_failed", error=str(e), query=query[:50])
        return []


def _parse_suggestions(raw_text: str) -> List[dict]:
    """Parse LLM response into validated follow-up suggestions.

    Handles common LLM output quirks:
    - Markdown code fences around JSON
    - Extra whitespace
    - Missing fields

    Args:
        raw_text: Raw text from LLM response.

    Returns:
        Validated list of {title, payload} dicts. Max 5 items.
    """
    # Strip markdown code fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("follow_up_json_parse_error", raw_preview=raw_text[:100])
        return []

    if not isinstance(parsed, list):
        return []

    # Validate and normalize each suggestion
    validated = []
    for item in parsed[:5]:  # Cap at 5 max
        if not isinstance(item, dict):
            continue
        title = item.get("title", "")
        payload = item.get("payload", "")
        if title and payload:
            validated.append({"title": str(title), "payload": str(payload)})

    return validated
