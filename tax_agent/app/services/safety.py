"""
Safety & Truncation Defense — Safety Module
=============================================

Centralizes all Gemini safety-related configuration:
- PRIMARY_SAFETY_SETTINGS  — BLOCK_ONLY_HIGH for all categories
- FALLBACK_SAFETY_SETTINGS — OFF for DANGEROUS_CONTENT (tax penalties)
- check_safety_block()     — Detects SAFETY blocks + empty candidates
- build_generation_config() — Wraps config dict with safety settings
"""

from typing import Tuple

import structlog

from google.genai import types

logger = structlog.get_logger(__name__)


# ─── Safety Settings Tiers ───────────────────────────────────────────────────

_HARM_CATEGORIES = [
    "HARM_CATEGORY_DANGEROUS_CONTENT",
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
]

PRIMARY_SAFETY_SETTINGS = [
    types.SafetySetting(category=cat, threshold="BLOCK_ONLY_HIGH")
    for cat in _HARM_CATEGORIES
]

FALLBACK_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=cat,
        threshold="OFF" if cat == "HARM_CATEGORY_DANGEROUS_CONTENT" else "BLOCK_ONLY_HIGH",
    )
    for cat in _HARM_CATEGORIES
]

# Georgian-language fallback message shown when all retry attempts fail
SAFETY_FALLBACK_MESSAGE = (
    "ბოდიშს გიხდით, ამ მომენტში ვერ ვპასუხობ თქვენს შეკითხვას. "
    "გთხოვთ, სცადოთ შეკითხვის გადაფორმულირება ან მიმართოთ rs.ge ვებგვერდს."
)


# ─── Safety Block Detection ──────────────────────────────────────────────────

def check_safety_block(response) -> Tuple[bool, str, str]:
    """Check if a Gemini response was safety-blocked or truncated.

    Handles three failure modes:
    1. response is None (API call failed silently)
    2. response.candidates is empty (Scoop Bug #26)
    3. finish_reason is SAFETY

    Returns:
        (is_blocked, reason, extracted_text)
        - is_blocked: True if the response was blocked/empty
        - reason: Human-readable reason string
        - extracted_text: Best-effort text extraction (empty if blocked)
    """
    # Guard: None response
    if response is None:
        return (True, "no_response", "")

    # Guard: empty candidates
    if not response.candidates:
        return (True, "no_candidates", "")

    candidate = response.candidates[0]
    finish_reason = candidate.finish_reason

    # Check for SAFETY block (string comparison works with google-genai enums)
    if finish_reason == "SAFETY":
        return (True, "finish_reason_safety", "")

    # Check for MAX_TOKENS truncation
    if finish_reason == "MAX_TOKENS":
        # Extract partial text for diagnostics, but flag as truncated
        partial = ""
        try:
            partial = response.text
        except Exception:
            pass
        return (True, "finish_reason_max_tokens", partial)

    # Extract text safely — response.text may raise on some finish reasons
    text = ""
    try:
        text = response.text
    except Exception:
        # Fallback: try manual part extraction
        try:
            if candidate.content and candidate.content.parts:
                text = "".join(
                    p.text for p in candidate.content.parts if hasattr(p, "text")
                )
        except Exception:
            pass

    return (False, str(finish_reason), text)


# ─── Generation Config Builder ───────────────────────────────────────────────

def build_generation_config(
    system_prompt: str,
    temperature: float,
    max_output_tokens: int,
    safety_level: str = "primary",
) -> dict:
    """Build a generation config dict with safety settings included.

    Args:
        system_prompt: The system instruction text.
        temperature: Sampling temperature.
        max_output_tokens: Max tokens in the response.
        safety_level: "primary" (BLOCK_ONLY_HIGH) or "fallback" (relaxed).

    Returns:
        Config dict ready for client.models.generate_content(config=...).
    """
    safety_settings = (
        FALLBACK_SAFETY_SETTINGS if safety_level == "fallback"
        else PRIMARY_SAFETY_SETTINGS
    )

    return {
        "system_instruction": system_prompt,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "safety_settings": safety_settings,
    }
