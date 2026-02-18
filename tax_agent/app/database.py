"""
Database Manager for Georgian Tax AI Agent
==========================================

Singleton connection manager with pooling and index creation.
Adapted from Scoop backend/app/memory/database.py
"""
import structlog
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import IndexModel, ASCENDING, DESCENDING, TEXT
from pymongo.errors import ConnectionFailure, OperationFailure

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Singleton database connection manager"""

    _instance: Optional["DatabaseManager"] = None
    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[AsyncIOMotorDatabase] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self, uri: str, database: str) -> None:
        """Initialize MongoDB connection with recommended settings"""
        if self._client is not None:
            return

        self._client = AsyncIOMotorClient(
            uri,
            # Connection Pool Settings
            minPoolSize=1,
            maxPoolSize=10,
            # Timeouts
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            serverSelectionTimeoutMS=5000,
            # Retry Settings
            retryWrites=True,
            retryReads=True,
        )
        self._db = self._client[database]

        # Verify connection
        try:
            await self._client.admin.command("ping")
            logger.info("database_connected", database=database)
        except ConnectionFailure as e:
            logger.error("database_connection_failed", error=str(e))
            raise

        # Create indexes
        await self._create_indexes()

    async def _create_indexes(self) -> None:
        """Create indexes for all 5 Tax Agent collections"""

        # =====================================================================
        # tax_articles — Georgian Tax Code articles
        # =====================================================================
        tax_articles_indexes = [
            # Unique article number lookup
            IndexModel([("article_number", ASCENDING)], unique=True),
            # Full-text search on Georgian + English titles
            IndexModel([("title_ka", TEXT), ("title_en", TEXT)]),
            # Filter by embedding model version
            IndexModel([("embedding_model", ASCENDING)]),
            # Filter by tax domain
            IndexModel([("domain", ASCENDING)]),
        ]

        # =====================================================================
        # definitions — Legal term definitions
        # =====================================================================
        definitions_indexes = [
            # Unique Georgian term lookup
            IndexModel([("term_ka", ASCENDING)], unique=True),
            # Filter by embedding model version
            IndexModel([("embedding_model", ASCENDING)]),
        ]

        # =====================================================================
        # metadata — Scrape status, sync state, etc.
        # =====================================================================
        metadata_indexes = [
            # One doc per metadata type (e.g., "scrape_status")
            IndexModel([("type", ASCENDING)], unique=True),
        ]

        # =====================================================================
        # conversations — Chat sessions with users
        # =====================================================================
        conversations_indexes = [
            # User's recent conversations (sorted newest first)
            IndexModel([("user_id", ASCENDING), ("updated_at", DESCENDING)]),
            # Auto-expire sessions after their expires_at timestamp
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]

        # =====================================================================
        # api_keys — Authentication keys (adapted from Scoop)
        # =====================================================================
        api_keys_indexes = [
            # Unique hash lookup for key validation
            IndexModel([("key_hash", ASCENDING)], unique=True),
            # User's active keys
            IndexModel([("user_id", ASCENDING)]),
            # Auto-expire keys after their expires_at timestamp
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]

        try:
            await self._db.tax_articles.create_indexes(tax_articles_indexes)
            await self._db.definitions.create_indexes(definitions_indexes)
            await self._db.metadata.create_indexes(metadata_indexes)
            await self._db.conversations.create_indexes(conversations_indexes)
            await self._db.api_keys.create_indexes(api_keys_indexes)
            logger.info("indexes_created", collections=5)
        except OperationFailure as e:
            logger.warning("index_creation_warning", error=str(e))

    async def disconnect(self) -> None:
        """Close database connection"""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("database_disconnected")

    @property
    def db(self) -> AsyncIOMotorDatabase:
        """Get database instance"""
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def ping(self) -> bool:
        """Health check — returns True if MongoDB responds"""
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False


# Global singleton instance
db_manager = DatabaseManager()
