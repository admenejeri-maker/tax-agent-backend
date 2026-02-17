"""
SSE Helpers — Shared Server-Sent Event formatting utilities.
"""

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def chunk_text(text: str, chunk_size: int = 80) -> list[str]:
    """Split text into chunks for simulated streaming."""
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
