"""
Sync Matsne Script

Version-aware sync: fetches latest Tax Code version from Matsne,
compares with stored version, and triggers re-seed if updated.

Idempotent — safe to run on cron or server startup.

Usage:
    python -m scripts.sync_matsne
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Path setup (allow running from project root) ───────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import db_manager
from app.models.definition import DefinitionStore
from app.models.tax_article import TaxArticleStore
from app.services.embedding_service import embed_and_store_all
from app.services.matsne_scraper import (
    detect_version,
    fetch_latest_html,
    scrape_and_store,
)
from config import settings

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> int:
    """Run the version-aware sync pipeline.

    Returns:
        Exit code: 0 on success (regardless of whether update was needed),
        1 on failure.
    """
    # ─── 1. Validate environment variables ───────────────────────────────
    # Log presence only — NEVER log secret values
    missing = []
    if not settings.mongodb_uri:
        missing.append("MONGODB_URI")
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")

    if missing:
        logger.error("env_vars_missing", extra={"missing": missing})
        return 1

    logger.info(
        "env_validated",
        extra={"mongodb_uri_set": True, "gemini_key_set": True},
    )

    # ─── 2. Connect to MongoDB (both params required) ────────────────────
    await db_manager.connect(
        uri=settings.mongodb_uri,
        database=settings.database_name,
    )

    try:
        # ─── 3. Read stored version (raw Motor — no Pydantic model) ──────
        doc = await db_manager.db.metadata.find_one(
            {"type": "tax_code_version"}, {"_id": 0},
        )
        stored_version = doc.get("publication") if doc else None
        logger.info(
            "sync_stored_version",
            extra={"stored_version": stored_version},
        )

        # ─── 4. Fetch latest version from Matsne ────────────────────────
        logger.info("sync_fetch_latest_start")
        html = await fetch_latest_html()
        latest_version = detect_version(html)
        logger.info(
            "sync_latest_version",
            extra={"latest_version": latest_version},
        )

        if latest_version is None:
            logger.warning("sync_version_detection_failed")
            # Update last_checked_at even on detection failure
            await _update_last_checked()
            return 0

        # ─── 5. Compare versions ────────────────────────────────────────
        needs_update = (
            stored_version is None
            or int(latest_version) > int(stored_version)
        )

        if not needs_update:
            logger.info(
                "sync_no_update_needed",
                extra={
                    "stored_version": stored_version,
                    "latest_version": latest_version,
                },
            )
            await _update_last_checked()
            return 0

        # ─── 6. Trigger full re-seed pipeline ───────────────────────────
        logger.info(
            "sync_update_detected",
            extra={
                "stored_version": stored_version,
                "latest_version": latest_version,
            },
        )

        article_store = TaxArticleStore()
        definition_store = DefinitionStore()

        # 6a. Scrape
        scrape_stats = await scrape_and_store(article_store, definition_store)
        version = scrape_stats.get("version")

        # 6b. Embed
        embed_stats = await embed_and_store_all(
            article_store, definition_store,
        )

        # 6c. Update metadata
        now = datetime.now(timezone.utc).isoformat()
        metadata_doc = {
            "type": "tax_code_version",
            "scrape_status": "completed",
            "embedding_model": settings.embedding_model,
            "articles_count": scrape_stats["articles_count"],
            "definitions_count": scrape_stats["definitions_count"],
            "synced_at": now,
            "last_checked_at": now,
        }
        if version is not None:
            metadata_doc["publication"] = int(version)

        await db_manager.db.metadata.update_one(
            {"type": "tax_code_version"},
            {"$set": metadata_doc},
            upsert=True,
        )

        logger.info(
            "sync_complete",
            extra={
                "articles": scrape_stats["articles_count"],
                "definitions": scrape_stats["definitions_count"],
                "articles_embedded": embed_stats["articles_embedded"],
                "definitions_embedded": embed_stats["definitions_embedded"],
                "new_version": version,
            },
        )
        return 0

    except Exception:
        logger.exception("sync_failed")
        return 1

    finally:
        # ─── 7. Always disconnect (F-NEW-6) ─────────────────────────────
        await db_manager.disconnect()


async def _update_last_checked() -> None:
    """Update only the last_checked_at timestamp in metadata."""
    now = datetime.now(timezone.utc).isoformat()
    await db_manager.db.metadata.update_one(
        {"type": "tax_code_version"},
        {"$set": {"last_checked_at": now}},
        upsert=True,
    )
    logger.info("sync_last_checked_updated")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
