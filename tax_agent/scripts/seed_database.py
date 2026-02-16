"""
Seed Database Script

Full pipeline: scrape all Tax Code articles → embed all → record metadata.
Idempotent — safe to re-run. Uses upsert for all writes.

Usage:
    python -m scripts.seed_database
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
from app.services.matsne_scraper import scrape_and_store
from config import settings

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> int:
    """Run the full seed pipeline.

    Returns:
        Exit code: 0 on success, 1 on failure.
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
        # ─── 3. Instantiate stores (plain classes) ───────────────────────
        article_store = TaxArticleStore()
        definition_store = DefinitionStore()

        # ─── 4. Scrape all articles + definitions ────────────────────────
        logger.info("seed_phase_scrape_start")
        scrape_stats = await scrape_and_store(article_store, definition_store)
        version = scrape_stats.get("version")
        logger.info(
            "seed_phase_scrape_complete",
            extra={
                "articles": scrape_stats["articles_count"],
                "definitions": scrape_stats["definitions_count"],
                "skipped": scrape_stats["skipped"],
                "errors": scrape_stats["errors"],
                "version": version,
            },
        )

        # ─── 5. Embed all articles + definitions ────────────────────────
        logger.info("seed_phase_embed_start")
        embed_stats = await embed_and_store_all(
            article_store, definition_store,
        )
        logger.info(
            "seed_phase_embed_complete",
            extra={
                "articles_embedded": embed_stats["articles_embedded"],
                "definitions_embedded": embed_stats["definitions_embedded"],
                "errors": embed_stats["errors"],
            },
        )

        # ─── 6. Upsert metadata (raw Motor — no Pydantic model) ─────────
        now = datetime.now(timezone.utc).isoformat()
        metadata_doc = {
            "type": "tax_code_version",
            "scrape_status": "completed",
            "embedding_model": settings.embedding_model,
            "articles_count": scrape_stats["articles_count"],
            "definitions_count": scrape_stats["definitions_count"],
            "seeded_at": now,
            "last_checked_at": now,
        }
        if version is not None:
            metadata_doc["publication"] = int(version)

        await db_manager.db.metadata.update_one(
            {"type": "tax_code_version"},
            {"$set": metadata_doc},
            upsert=True,
        )
        logger.info("seed_metadata_saved", extra={"version": version})

        # ─── 7. Canary check ────────────────────────────────────────────
        canary = await article_store.find_by_number(160)
        if canary is None:
            logger.warning(
                "seed_canary_missing",
                extra={"article_number": 160},
            )
        else:
            logger.info(
                "seed_canary_verified",
                extra={"article_number": 160},
            )

        # ─── 8. Summary ─────────────────────────────────────────────────
        logger.info(
            "seed_complete",
            extra={
                "articles": scrape_stats["articles_count"],
                "definitions": scrape_stats["definitions_count"],
                "articles_embedded": embed_stats["articles_embedded"],
                "definitions_embedded": embed_stats["definitions_embedded"],
                "version": version,
            },
        )
        return 0

    except Exception:
        logger.exception("seed_failed")
        return 1

    finally:
        # ─── 9. Always disconnect (F-NEW-6) ─────────────────────────────
        await db_manager.disconnect()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
