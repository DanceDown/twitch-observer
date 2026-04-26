from __future__ import annotations

"""PostgreSQL message persistence."""

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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
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
        self.database.connect()
        assert self.database.connection is not None
        with self.database.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT username, content, timestamp
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
                username=str(row[0]),
                content=str(row[1]),
                timestamp=row[2],
            )
            for row in rows
        ]

    @staticmethod
    def _build_fallback_message_id(event: TwitchChatMessageEvent) -> str:
        """Build a deterministic fallback ID when Twitch did not provide one."""
        timestamp = event.sent_at.isoformat()
        return f"{event.channel_login}:{event.author_login}:{timestamp}:{hash(event.content)}"

