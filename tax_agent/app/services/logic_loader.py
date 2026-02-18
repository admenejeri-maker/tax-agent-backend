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
        domain: Tax domain from router (e.g. "VAT", "INDIVIDUAL_INCOME", "CORPORATE_TAX").

    Returns:
        Markdown string with reasoning rules, or None.
    """
    if not settings.logic_rules_enabled:
        return None

    if domain not in _cache:
        path = LOGIC_DIR / f"{domain.lower()}_rules.md"
        # Guard: resolved path must stay within LOGIC_DIR
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(LOGIC_DIR.resolve()):
                logger.warning("logic_loader_path_traversal", domain=domain)
                return None
        except (ValueError, OSError):
            return None
        try:
            if path.exists():
                _cache[domain] = path.read_text(encoding="utf-8")
            # Don't cache missing files — allows hot-reload
        except (PermissionError, UnicodeDecodeError, OSError) as exc:
            logger.warning("logic_loader_read_error", domain=domain, error=str(exc))
            # Don't cache errors either — allows retry

    result = _cache.get(domain)
    if result is not None:
        logger.info("logic_rules_loaded", domain=domain, chars=len(result))
    else:
        logger.debug("logic_rules_not_found", domain=domain)

    return result
