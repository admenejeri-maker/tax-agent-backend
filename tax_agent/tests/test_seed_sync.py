"""
Tests for seed_database.py and sync_matsne.py

Tests orchestration logic and metadata persistence.
All network calls are mocked — no real HTTP or DB.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Mock settings with required env vars populated."""
    with patch("scripts.seed_database.settings") as seed_settings, \
         patch("scripts.sync_matsne.settings") as sync_settings:
        for s in (seed_settings, sync_settings):
            s.mongodb_uri = "mongodb://test:27017"
            s.database_name = "test_db"
            s.gemini_api_key = "test-key"
            s.embedding_model = "gemini-embedding-001"
            s.matsne_request_delay = 0
        yield seed_settings, sync_settings


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager with metadata collection."""
    with patch("scripts.seed_database.db_manager") as seed_db, \
         patch("scripts.sync_matsne.db_manager") as sync_db:
        for db in (seed_db, sync_db):
            db.connect = AsyncMock()
            db.disconnect = AsyncMock()
            # Mock metadata collection
            mock_metadata = MagicMock()
            mock_metadata.update_one = AsyncMock()
            mock_metadata.find_one = AsyncMock(return_value=None)
            db.db = MagicMock()
            db.db.metadata = mock_metadata
        yield seed_db, sync_db


@pytest.fixture
def mock_scrape():
    """Mock scrape_and_store to return stats without network calls."""
    stats = {
        "articles_count": 312,
        "definitions_count": 45,
        "skipped": 5,
        "errors": 0,
        "version": "239",
    }
    with patch(
        "scripts.seed_database.scrape_and_store",
        new_callable=AsyncMock,
        return_value=stats,
    ) as seed_scrape, patch(
        "scripts.sync_matsne.scrape_and_store",
        new_callable=AsyncMock,
        return_value=stats,
    ) as sync_scrape:
        yield seed_scrape, sync_scrape


@pytest.fixture
def mock_embed():
    """Mock embed_and_store_all to return stats without API calls."""
    stats = {
        "articles_embedded": 312,
        "definitions_embedded": 45,
        "errors": 0,
    }
    with patch(
        "scripts.seed_database.embed_and_store_all",
        new_callable=AsyncMock,
        return_value=stats,
    ) as seed_embed, patch(
        "scripts.sync_matsne.embed_and_store_all",
        new_callable=AsyncMock,
        return_value=stats,
    ) as sync_embed:
        yield seed_embed, sync_embed


@pytest.fixture
def mock_article_store():
    """Mock TaxArticleStore."""
    with patch("scripts.seed_database.TaxArticleStore") as seed_cls, \
         patch("scripts.sync_matsne.TaxArticleStore") as sync_cls:
        store = MagicMock()
        store.find_by_number = AsyncMock(
            return_value={"article_number": 160, "title": "test"},
        )
        seed_cls.return_value = store
        sync_cls.return_value = store
        yield store


@pytest.fixture
def mock_definition_store():
    """Mock DefinitionStore."""
    with patch("scripts.seed_database.DefinitionStore") as seed_cls, \
         patch("scripts.sync_matsne.DefinitionStore") as sync_cls:
        store = MagicMock()
        seed_cls.return_value = store
        sync_cls.return_value = store
        yield store


@pytest.fixture
def mock_fetch_latest():
    """Mock fetch_latest_html for sync script."""
    html = '<html>publication=240</html>'
    with patch(
        "scripts.sync_matsne.fetch_latest_html",
        new_callable=AsyncMock,
        return_value=html,
    ) as mock:
        yield mock


# ─── T1: Seed full run — metadata created ────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_creates_metadata(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
):
    """T1: After seed, metadata doc is upserted with scrape_status=completed."""
    from scripts.seed_database import main

    exit_code = await main()

    assert exit_code == 0

    seed_db, _ = mock_db_manager
    # Verify metadata.update_one was called
    seed_db.db.metadata.update_one.assert_called_once()

    # Extract the $set argument
    call_args = seed_db.db.metadata.update_one.call_args
    filter_doc = call_args[0][0]
    update_doc = call_args[0][1]

    assert filter_doc == {"type": "tax_code_version"}
    set_doc = update_doc["$set"]
    assert set_doc["scrape_status"] == "completed"
    assert set_doc["publication"] == 239
    assert set_doc["articles_count"] == 312
    assert set_doc["definitions_count"] == 45
    assert set_doc["embedding_model"] == "gemini-embedding-001"
    assert "seeded_at" in set_doc


# ─── T2: Re-run seed — idempotent ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_idempotent_rerun(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
):
    """T2: Running seed twice still results in correct article counts."""
    from scripts.seed_database import main

    exit_code_1 = await main()
    exit_code_2 = await main()

    assert exit_code_1 == 0
    assert exit_code_2 == 0

    # scrape_and_store was called twice (once per run)
    seed_scrape, _ = mock_scrape
    assert seed_scrape.call_count == 2


# ─── T3: Canary check ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_canary_check(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
):
    """T3: After seed, canary article 160 is verified via find_by_number."""
    from scripts.seed_database import main

    exit_code = await main()

    assert exit_code == 0
    mock_article_store.find_by_number.assert_called_once_with(160)


# ─── T4: Metadata document shape ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_metadata_shape(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
):
    """T4: Metadata doc has all required keys with correct types."""
    from scripts.seed_database import main

    exit_code = await main()
    assert exit_code == 0

    seed_db, _ = mock_db_manager
    call_args = seed_db.db.metadata.update_one.call_args
    set_doc = call_args[0][1]["$set"]

    # Required keys
    assert set_doc["type"] == "tax_code_version"
    assert isinstance(set_doc["publication"], int)
    assert set_doc["publication"] > 200
    assert set_doc["scrape_status"] in ("completed", "in_progress", "failed")
    assert isinstance(set_doc["embedding_model"], str)
    assert isinstance(set_doc["articles_count"], int)
    assert isinstance(set_doc["definitions_count"], int)
    assert isinstance(set_doc["seeded_at"], str)
    assert isinstance(set_doc["last_checked_at"], str)


# ─── T5: Sync with same version — no re-scrape ──────────────────────────────


@pytest.mark.asyncio
async def test_sync_no_update_needed(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
):
    """T5: When stored version >= latest, sync logs 'no update needed'
    and does NOT trigger scrape_and_store."""
    _, sync_db = mock_db_manager

    # Stored version 240 matches latest version 240
    sync_db.db.metadata.find_one = AsyncMock(
        return_value={"publication": 240, "type": "tax_code_version"},
    )

    # Latest version returns 240
    html = '<html>publication=240</html>'
    with patch(
        "scripts.sync_matsne.fetch_latest_html",
        new_callable=AsyncMock,
        return_value=html,
    ):
        from scripts.sync_matsne import main

        exit_code = await main()

    assert exit_code == 0

    # scrape_and_store should NOT have been called
    _, sync_scrape = mock_scrape
    sync_scrape.assert_not_called()


# ─── T6: Sync triggers re-seed when new version detected ────────────────────


@pytest.mark.asyncio
async def test_sync_triggers_reseed_on_new_version(
    mock_settings,
    mock_db_manager,
    mock_scrape,
    mock_embed,
    mock_article_store,
    mock_definition_store,
    mock_fetch_latest,
):
    """When latest version (240) > stored (239), sync triggers full pipeline."""
    _, sync_db = mock_db_manager

    # Stored version is 239
    sync_db.db.metadata.find_one = AsyncMock(
        return_value={"publication": 239, "type": "tax_code_version"},
    )

    from scripts.sync_matsne import main

    exit_code = await main()

    assert exit_code == 0

    # scrape_and_store SHOULD have been called
    _, sync_scrape = mock_scrape
    sync_scrape.assert_called_once()

    # embed_and_store_all SHOULD have been called
    _, sync_embed = mock_embed
    sync_embed.assert_called_once()


# ─── T7: Seed fails on missing env vars ─────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_fails_on_missing_env():
    """Seed exits with code 1 if MONGODB_URI is missing."""
    with patch("scripts.seed_database.settings") as mock_s:
        mock_s.mongodb_uri = ""
        mock_s.gemini_api_key = "test-key"

        from scripts.seed_database import main
        exit_code = await main()

    assert exit_code == 1


# ─── T8: Disconnect always called (even on error) ───────────────────────────


@pytest.mark.asyncio
async def test_seed_disconnect_on_error(
    mock_settings,
    mock_db_manager,
    mock_article_store,
    mock_definition_store,
):
    """disconnect() is called in finally block even when scrape fails."""
    with patch(
        "scripts.seed_database.scrape_and_store",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network failure"),
    ):
        from scripts.seed_database import main

        exit_code = await main()

    assert exit_code == 1

    seed_db, _ = mock_db_manager
    seed_db.disconnect.assert_called_once()
