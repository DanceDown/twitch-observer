"""PostgreSQL message persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.events.twitch_events import TwitchChatMessageEvent

from ..records import RecentMessageRecord
from ..repositories import MessageRepository
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresMessageRepository(MessageRepository):
    """Store normalized Twitch chat messages in PostgreSQL."""

    database: PostgresDatabase

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        """Persist one incoming Twitch message if it has not been stored yet."""
        await self._save_message(event, is_bot=False)

    async def save_bot_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        """Persist one bot-originated Twitch message if it has not been stored yet."""
        await self._save_message(event, is_bot=True)

    async def _save_message(
        self,
        event: TwitchChatMessageEvent,
        *,
        is_bot: bool,
    ) -> None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO message (
                    message_id,
                    twitch_channel_id,
                    timestamp,
                    twitch_user_id,
                    username,
                    content,
                    is_reply_to,
                    is_bot
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    (SELECT message_id FROM message WHERE message_id = %s),
                    %s
                )
                ON CONFLICT (message_id) DO NOTHING
                """,
                self._build_message_params(event, is_bot=is_bot),
            )

    async def flush_write_batch(
        self,
        *,
        message_events: tuple[TwitchChatMessageEvent, ...],
        thread_matches: tuple[tuple[int, TwitchChatMessageEvent], ...],
    ) -> None:
        """Persist one batched write snapshot for messages and thread matches."""
        if not message_events and not thread_matches:
            return
        async with self.database.async_transaction() as connection:
            async with connection.cursor() as cursor:
                if message_events:
                    await cursor.executemany(
                        """
                        INSERT INTO message (
                            message_id,
                            twitch_channel_id,
                            timestamp,
                            twitch_user_id,
                            username,
                            content,
                            is_reply_to,
                            is_bot
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            (SELECT message_id FROM message WHERE message_id = %s),
                            %s
                        )
                        ON CONFLICT (message_id) DO NOTHING
                        """,
                        tuple(self._build_message_params(event, is_bot=False) for event in message_events),
                    )
                if thread_matches:
                    await cursor.executemany(
                        """
                        INSERT INTO thread_message_match (thread_id, message_id)
                        SELECT %s, message_id
                        FROM message
                        WHERE message_id = %s
                        ON CONFLICT (thread_id, message_id) DO NOTHING
                        """,
                        tuple((thread_id, self._resolve_message_id(event)) for thread_id, event in thread_matches),
                    )

    async def mark_message_matched_in_thread(
        self,
        *,
        thread_id: int,
        event: TwitchChatMessageEvent,
    ) -> None:
        """Persist that one stored Twitch message matched inside one Discord thread."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO thread_message_match (thread_id, message_id)
                SELECT %s, message_id
                FROM message
                WHERE message_id = %s
                ON CONFLICT (thread_id, message_id) DO NOTHING
                """,
                (thread_id, self._resolve_message_id(event)),
            )

    async def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        """Load recent Twitch messages for presence updates or lightweight recency-based features."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT message_id, twitch_channel_id, username, content, timestamp
                FROM message
                WHERE timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (since, limit),
            )
            rows = await cursor.fetchall()
        return [
            RecentMessageRecord(
                message_id=str(row[0]),
                twitch_channel_id=str(row[1]),
                username=str(row[2]),
                content=str(row[3]),
                timestamp=row[4],
            )
            for row in rows
        ]

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        """Load recent Twitch messages for one tracked channel."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT message_id, twitch_channel_id, username, content, timestamp
                FROM message
                WHERE twitch_channel_id = %s
                  AND timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (twitch_channel_id, since, limit),
            )
            rows = await cursor.fetchall()
        return [
            RecentMessageRecord(
                message_id=str(row[0]),
                twitch_channel_id=str(row[1]),
                username=str(row[2]),
                content=str(row[3]),
                timestamp=row[4],
            )
            for row in rows
        ]

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        """Load recent Twitch messages that matched inside one Discord thread."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT m.message_id, m.twitch_channel_id, m.username, m.content, m.timestamp
                FROM thread_message_match AS tmm
                JOIN message AS m ON m.message_id = tmm.message_id
                WHERE tmm.thread_id = %s
                  AND m.timestamp >= %s
                ORDER BY m.timestamp DESC
                LIMIT %s
                """,
                (thread_id, since, limit),
            )
            rows = await cursor.fetchall()
        return [
            RecentMessageRecord(
                message_id=str(row[0]),
                twitch_channel_id=str(row[1]),
                username=str(row[2]),
                content=str(row[3]),
                timestamp=row[4],
            )
            for row in rows
        ]

    async def get_thread_message(
        self,
        *,
        thread_id: int,
        message_id: str,
    ) -> RecentMessageRecord | None:
        """Load one stored Twitch message if it matched inside one Discord thread."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT m.message_id, m.twitch_channel_id, m.username, m.content, m.timestamp
                FROM thread_message_match AS tmm
                JOIN message AS m ON m.message_id = tmm.message_id
                WHERE tmm.thread_id = %s
                  AND m.message_id = %s
                LIMIT 1
                """,
                (thread_id, message_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return RecentMessageRecord(
            message_id=str(row[0]),
            twitch_channel_id=str(row[1]),
            username=str(row[2]),
            content=str(row[3]),
            timestamp=row[4],
        )

    @staticmethod
    def _build_fallback_message_id(event: TwitchChatMessageEvent) -> str:
        raise ValueError("Twitch IRC message is missing message_id.")

    @classmethod
    def _resolve_message_id(cls, event: TwitchChatMessageEvent) -> str:
        return event.message_id or cls._build_fallback_message_id(event)

    @classmethod
    def _build_message_params(
        cls,
        event: TwitchChatMessageEvent,
        *,
        is_bot: bool,
    ) -> tuple[object, ...]:
        return (
            cls._resolve_message_id(event),
            event.broadcaster_id or event.channel_login,
            event.sent_at,
            event.author_id or event.author_login,
            event.author_display_name or event.author_login,
            event.content,
            event.reply_parent_message_id,
            is_bot,
        )
