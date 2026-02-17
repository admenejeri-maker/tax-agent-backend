"""
Chain-of-Logic Loader — Step 3
================================
Lazy-loads domain-specific reasoning rules from Markdown files.
Files live in data/logic/<domain>_rules.md and are cached after first read.
"""
from pathlib import Path
from typing import Optional

import structlog

from config import settings

logger = structlog.get_logger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
# Patchable in tests via monkeypatch.setattr
LOGIC_DIR: Path = Path(__file__).parent.parent.parent / "data" / "logic"

# ─── Cache ───────────────────────────────────────────────────────────────────
_cache: dict[str, Optional[str]] = {}


def clear_cache() -> None:
    """Reset the rules cache. Used in tests and after hot-reload."""
    _cache.clear()


def get_logic_rules(domain: str) -> Optional[str]:
    """Return CoL rules markdown for a domain, or None.

    Returns None when:
    - logic_rules_enabled flag is False
    - No rule file exists for the domain
    - File read fails (permission/encoding error)

    Args:
        domain: Tax domain from router (e.g. "VAT", "INCOME_TAX").

    Returns:
        Markdown string with reasoning rules, or None.
    """
    if not settings.logic_rules_enabled:
        return None

    if domain not in _cache:
        path = LOGIC_DIR / f"{domain.lower()}_rules.md"
        try:
            _cache[domain] = path.read_text(encoding="utf-8") if path.exists() else None
        except (PermissionError, UnicodeDecodeError, OSError) as exc:
            logger.warning("logic_loader_read_error", domain=domain, error=str(exc))
            _cache[domain] = None

        if _cache[domain] is not None:
            logger.info("logic_rules_loaded", domain=domain, chars=len(_cache[domain]))
        else:
            logger.debug("logic_rules_not_found", domain=domain)

    return _cache[domain]
