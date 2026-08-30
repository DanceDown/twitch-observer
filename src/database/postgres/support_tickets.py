"""PostgreSQL repository for Discord support tickets."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import SupportTicketRecord
from ..repositories import SupportTicketRepository
from ._utils import require_row
from .database import PostgresDatabase


SupportTicketRow = tuple


@dataclass(slots=True)
class PostgresSupportTicketRepository(SupportTicketRepository):
    """Store and update support tickets in PostgreSQL."""

    database: PostgresDatabase

    async def create_ticket(
        self,
        *,
        source_discord_channel_id: int,
        requester_discord_user_id: int,
        category: str,
        title: str,
        description: str,
        language: str,
    ) -> SupportTicketRecord:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                f"""
                INSERT INTO support_ticket (
                    source_discord_channel_id,
                    requester_discord_user_id,
                    category,
                    title,
                    description,
                    language
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {self._columns()}
                """,
                (
                    source_discord_channel_id,
                    requester_discord_user_id,
                    category,
                    title,
                    description,
                    language,
                ),
            )
            row = require_row(await cursor.fetchone(), operation="support_ticket.create_ticket")
        return self._build_record(row)

    async def set_support_message_id(
        self,
        *,
        ticket_id: int,
        support_message_id: int,
    ) -> SupportTicketRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                f"""
                UPDATE support_ticket
                SET support_message_id = %s,
                    updated_at = NOW()
                WHERE ticket_id = %s
                RETURNING {self._columns()}
                """,
                (support_message_id, ticket_id),
            )
            row = await cursor.fetchone()
        return self._build_record(row) if row is not None else None

    async def get_ticket(self, *, ticket_id: int) -> SupportTicketRecord | None:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT {self._columns()}
                FROM support_ticket
                WHERE ticket_id = %s
                """,
                (ticket_id,),
            )
            row = await cursor.fetchone()
        return self._build_record(row) if row is not None else None

    async def list_open_tickets_with_messages(self) -> list[SupportTicketRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT {self._columns()}
                FROM support_ticket
                WHERE status = 'open'
                  AND support_message_id IS NOT NULL
                ORDER BY ticket_id
                """,
                (),
            )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def answer_ticket(
        self,
        *,
        ticket_id: int,
        responder_discord_user_id: int,
        response_subject: str,
        response_body: str,
    ) -> SupportTicketRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                f"""
                UPDATE support_ticket
                SET status = 'answered',
                    response_subject = %s,
                    response_body = %s,
                    responded_by_discord_user_id = %s,
                    responded_at = NOW(),
                    updated_at = NOW()
                WHERE ticket_id = %s
                  AND status = 'open'
                RETURNING {self._columns()}
                """,
                (response_subject, response_body, responder_discord_user_id, ticket_id),
            )
            row = await cursor.fetchone()
        return self._build_record(row) if row is not None else None

    async def close_ticket(
        self,
        *,
        ticket_id: int,
        closer_discord_user_id: int,
    ) -> SupportTicketRecord | None:
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                f"""
                UPDATE support_ticket
                SET status = 'closed',
                    closed_by_discord_user_id = %s,
                    closed_at = NOW(),
                    updated_at = NOW()
                WHERE ticket_id = %s
                  AND status = 'open'
                RETURNING {self._columns()}
                """,
                (closer_discord_user_id, ticket_id),
            )
            row = await cursor.fetchone()
        return self._build_record(row) if row is not None else None

    @staticmethod
    def _columns() -> str:
        return """
            ticket_id,
            source_discord_channel_id,
            requester_discord_user_id,
            category,
            title,
            description,
            status,
            language,
            support_message_id,
            response_subject,
            response_body,
            responded_by_discord_user_id,
            responded_at,
            closed_by_discord_user_id,
            closed_at,
            created_at,
            updated_at
        """

    @staticmethod
    def _build_record(row: SupportTicketRow) -> SupportTicketRecord:
        return SupportTicketRecord(
            ticket_id=int(row[0]),
            source_discord_channel_id=int(row[1]),
            requester_discord_user_id=int(row[2]),
            category=str(row[3]),
            title=str(row[4]),
            description=str(row[5]),
            status=str(row[6]),
            language=str(row[7]),
            support_message_id=int(row[8]) if row[8] is not None else None,
            response_subject=str(row[9]) if row[9] is not None else None,
            response_body=str(row[10]) if row[10] is not None else None,
            responded_by_discord_user_id=int(row[11]) if row[11] is not None else None,
            responded_at=row[12],
            closed_by_discord_user_id=int(row[13]) if row[13] is not None else None,
            closed_at=row[14],
            created_at=row[15],
            updated_at=row[16],
        )
