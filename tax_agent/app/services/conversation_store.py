"""
Conversation Store — Task 7
============================

Session persistence for the Georgian Tax AI Agent.
Adapted from Scoop backend/app/memory/conversation_store.py (simplified).

Key differences from Scoop:
- No Gemini Content ↔ BSON conversion (we store plain text)
- No pruning / summarization (deferred to Phase 2)
- No UserStore dependency
- IDOR protection: all queries filter by user_id
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from app.database import db_manager

logger = structlog.get_logger(__name__)


class ConversationStore:
    """Manages conversation sessions in MongoDB.

    All methods require user_id for IDOR protection — a user
    can only access their own sessions.
    """

    COLLECTION = "conversations"
    MAX_TITLE_LENGTH = 30

    # ─── Session Lifecycle ────────────────────────────────────────────────

    async def create_session(self, user_id: str) -> str:
        """Create a new conversation session.

        Args:
            user_id: Authenticated user identifier from API key.

        Returns:
            New conversation_id (UUID4).
        """
        conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        doc = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": "ახალი საუბარი",  # "New conversation" — updated after first turn
            "turns": [],
            "turn_count": 0,
            "created_at": now,
            "updated_at": now,
        }

        await self._collection.insert_one(doc)
        logger.info(
            "session_created",
            conversation_id=conversation_id,
            user_id=user_id[:8] + "...",
        )
        return conversation_id

    async def add_turn(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        sources: list | None = None,
    ) -> bool:
        """Append a turn to a conversation.

        Args:
            conversation_id: Session to append to.
            user_id: Must match session owner (IDOR protection).
            role: "user" or "assistant".
            content: Message text.
            sources: Optional list of citation source dicts.

        Returns:
            True if the turn was saved, False if session not found/not owned.
        """
        now = datetime.now(timezone.utc)
        turn = {
            "role": role,
            "content": content,
            "timestamp": now.isoformat(),
        }
        if sources:
            turn["sources"] = sources

        result = await self._collection.update_one(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,  # IDOR: only owner can write
            },
            {
                "$push": {"turns": turn},
                "$set": {"updated_at": now},
                "$inc": {"turn_count": 1},
            },
        )

        if result.matched_count == 0:
            logger.warning(
                "add_turn_no_match",
                conversation_id=conversation_id,
                user_id=user_id[:8] + "...",
            )
            return False

        # Update title from first user message
        if role == "user":
            session = await self._collection.find_one(
                {"conversation_id": conversation_id, "user_id": user_id},
                {"turns": 1, "title": 1},
            )
            if session and session.get("title") == "ახალი საუბარი":
                title = self._extract_title(content)
                await self._collection.update_one(
                    {"conversation_id": conversation_id, "user_id": user_id},
                    {"$set": {"title": title}},
                )

        return True

    # ─── Read Operations ──────────────────────────────────────────────────

    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Load conversation history.

        Args:
            conversation_id: Session to load.
            user_id: Must match session owner (IDOR protection).

        Returns:
            Full session document or None if not found/not owned.
        """
        session = await self._collection.find_one(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,  # IDOR: only owner can read
            }
        )

        if not session:
            logger.debug(
                "session_not_found",
                conversation_id=conversation_id,
                user_id=user_id[:8] + "...",
            )
            return None

        return session

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List user's conversations, newest first.

        Args:
            user_id: Scoped to this user only.
            limit: Max sessions to return.

        Returns:
            List of session summaries (no turns, just metadata).
        """
        cursor = self._collection.find(
            {"user_id": user_id},
            {
                "conversation_id": 1,
                "title": 1,
                "created_at": 1,
                "updated_at": 1,
                "turn_count": 1,
                "_id": 0,
            },
        ).sort("updated_at", -1).limit(limit)

        sessions = []
        async for doc in cursor:
            sessions.append({
                "conversation_id": doc["conversation_id"],
                "title": doc.get("title", "ახალი საუბარი"),
                "created_at": doc["created_at"].isoformat(),
                "updated_at": doc["updated_at"].isoformat(),
                "turn_count": doc.get("turn_count", 0),
            })
        return sessions

    # ─── Delete Operations ────────────────────────────────────────────────

    async def clear_session(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        """Delete a conversation session.

        Args:
            conversation_id: Session to delete.
            user_id: Must match session owner (IDOR protection).

        Returns:
            True if deleted, False if not found/not owned.
        """
        result = await self._collection.delete_one(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,  # IDOR: only owner can delete
            }
        )

        deleted = result.deleted_count > 0
        logger.info(
            "session_cleared",
            conversation_id=conversation_id,
            deleted=deleted,
        )
        return deleted

    async def delete_user_data(self, user_id: str) -> int:
        """Delete ALL sessions for a user in one atomic operation.

        Args:
            user_id: User whose data to purge.

        Returns:
            Number of sessions deleted.
        """
        result = await self._collection.delete_many({"user_id": user_id})

        logger.info(
            "user_data_deleted",
            user_id=user_id[:8] + "...",
            deleted_count=result.deleted_count,
        )
        return result.deleted_count

    # ─── Helpers ──────────────────────────────────────────────────────────

    @property
    def _collection(self):
        """Lazy access to conversations collection via singleton."""
        return db_manager.db[self.COLLECTION]

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract conversation title from first user message.

        Truncates to MAX_TITLE_LENGTH chars without breaking mid-character
        (Python handles Unicode slicing correctly).
        """
        text = text.strip()
        max_len = ConversationStore.MAX_TITLE_LENGTH
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text


# Global singleton instance
conversation_store = ConversationStore()
