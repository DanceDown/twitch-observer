"""PostgreSQL message persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.events.event_types import TwitchChatMessageEvent

from ..records import RecentMessageRecord
from ..repositories import MessageRepository
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresMessageRepository(MessageRepository):
    """Store normalized Twitch chat messages in PostgreSQL."""

    database: PostgresDatabase

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        """Persist one incoming Twitch message if it has not been stored yet."""
        with self.database.cursor() as cursor:
            cursor.execute(
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
                    FALSE
                )
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    event.message_id or self._build_fallback_message_id(event),
                    event.broadcaster_id or event.channel_login,
                    event.sent_at,
                    event.author_id or event.author_login,
                    event.author_display_name or event.author_login,
                    event.content,
                    event.reply_parent_message_id,
                ),
            )

    def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        """Load recent Twitch messages for presence updates or lightweight recency-based features."""
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT message_id, twitch_channel_id, username, content, timestamp
                FROM message
                WHERE timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (since, limit),
            )
            rows = cursor.fetchall()
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

    def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        """Load recent Twitch messages for one tracked channel."""
        with self.database.cursor() as cursor:
            cursor.execute(
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
            rows = cursor.fetchall()
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

    @staticmethod
    def _build_fallback_message_id(event: TwitchChatMessageEvent) -> str:
        """Build a deterministic fallback ID when Twitch did not provide one."""
        timestamp = event.sent_at.isoformat()
        return f"{event.channel_login}:{event.author_login}:{timestamp}:{hash(event.content)}"
