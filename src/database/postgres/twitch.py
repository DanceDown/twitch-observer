"""PostgreSQL repositories for Twitch account and cache state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg.types.json import Jsonb

from ..records import (
    TwitchAccountCreate,
    TwitchAccountRecord,
    TwitchAccountUpdate,
    TwitchDeviceFlowRecord,
    TwitchDeviceFlowUpsert,
    TwitchUserCacheRecord,
    TwitchUserCacheUpsert,
)
from ..repositories import TwitchAccountRepository, TwitchDeviceFlowRepository, TwitchUserCacheRepository
from ._utils import require_row, require_value
from .database import PostgresDatabase

JsonStringList = list[str] | tuple[str, ...] | None
TwitchAccountRow = tuple[int, int, str, str, str, str | None, str | None, datetime | None, JsonStringList, str | None]
TwitchDeviceFlowRow = tuple[int | None, int, str, str, str, int, datetime, JsonStringList, str, str | None, datetime | None]
TwitchUserCacheRow = tuple[str, str, str, str | None, str | None, datetime]


@dataclass(slots=True)
class PostgresTwitchAccountRepository(TwitchAccountRepository):
    """Store and retrieve linked Twitch user accounts."""

    database: PostgresDatabase

    async def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
        """Return one linked Twitch account by internal ID."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                       access_token, refresh_token, expires_at, scope, token_type
                FROM twitch_account
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    async def create_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:
        """Insert a linked Twitch account with validated token data."""
        token = account.token
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO twitch_account (
                    discord_user_id, twitch_user_id, twitch_login, client_id,
                    updated_at, access_token, refresh_token, expires_at, scope, token_type
                )
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
                RETURNING account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                          access_token, refresh_token, expires_at, scope, token_type
                """,
                (
                    account.discord_user_id,
                    token.twitch_user_id,
                    token.twitch_login,
                    token.client_id,
                    token.access_token,
                    token.refresh_token,
                    token.expires_at,
                    Jsonb(list(token.scope)),
                    token.token_type,
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_account.create_account")
        return self._build_account_record(row)

    async def update_account(self, account: TwitchAccountUpdate) -> TwitchAccountRecord | None:
        """Replace token data for an existing linked Twitch account."""
        token = account.token
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE twitch_account
                SET twitch_user_id = %s,
                    twitch_login = %s,
                    client_id = %s,
                    updated_at = NOW(),
                    access_token = %s,
                    refresh_token = %s,
                    expires_at = %s,
                    scope = %s,
                    token_type = %s
                WHERE account_id = %s
                RETURNING account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                          access_token, refresh_token, expires_at, scope, token_type
                """,
                (
                    token.twitch_user_id,
                    token.twitch_login,
                    token.client_id,
                    token.access_token,
                    token.refresh_token,
                    token.expires_at,
                    Jsonb(list(token.scope)),
                    token.token_type,
                    account.account_id,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    async def remove_by_account_id(self, account_id: int) -> bool:
        """Delete one linked Twitch account by internal ID."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM twitch_account
                WHERE account_id = %s
                RETURNING account_id
                """,
                (account_id,),
            )
            row = await cursor.fetchone()
        return row is not None

    async def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:
        """Return the newest linked Twitch account for one Discord user."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                       access_token, refresh_token, expires_at, scope, token_type
                FROM twitch_account
                WHERE discord_user_id = %s
                ORDER BY updated_at DESC NULLS LAST, account_id DESC
                LIMIT 1
                """,
                (discord_user_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    async def upsert_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:
        """Create or update the linked Twitch account for a Discord user."""
        existing = await self.get_by_discord_user_id(account.discord_user_id)
        if existing is None:
            return await self.create_account(account)
        updated = await self.update_account(
            TwitchAccountUpdate(
                account_id=existing.account_id,
                token=account.token,
            )
        )
        return require_value(updated, operation="twitch_account.upsert_account")

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        """Delete the newest linked Twitch account for one Discord user."""
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return await self.remove_by_account_id(existing.account_id)

    async def list_accounts(self) -> list[TwitchAccountRecord]:
        """Return all linked Twitch accounts, newest first."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT account_id, discord_user_id, twitch_user_id, twitch_login, client_id,
                       access_token, refresh_token, expires_at, scope, token_type
                FROM twitch_account
                ORDER BY updated_at DESC NULLS LAST, account_id DESC
                """
            )
            rows = await cursor.fetchall()
        return [self._build_account_record(row) for row in rows]

    @staticmethod
    def _build_account_record(row: TwitchAccountRow) -> TwitchAccountRecord:
        scopes = tuple(row[8] or [])
        return TwitchAccountRecord(
            account_id=int(row[0]),
            discord_user_id=int(row[1]),
            twitch_user_id=row[2],
            twitch_login=row[3],
            client_id=row[4],
            access_token=row[5],
            refresh_token=row[6],
            expires_at=row[7].isoformat() if row[7] is not None else None,
            scope=scopes,
            token_type=row[9],
        )


@dataclass(slots=True)
class PostgresTwitchDeviceFlowRepository(TwitchDeviceFlowRepository):
    """Store and retrieve pending Twitch Device Code authorizations."""

    database: PostgresDatabase

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> TwitchDeviceFlowRecord | None:
        """Return a pending or failed device flow for one Discord channel."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def upsert_pending_flow(self, flow: TwitchDeviceFlowUpsert) -> TwitchDeviceFlowRecord:
        """Create or reset a pending Twitch device-code flow."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO twitch_device_flow (
                    discord_channel_id, discord_user_id, device_code, user_code, verification_uri,
                    interval_seconds, expires_at, scope, status, last_error,
                    last_polled_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NULL, NULL, NOW())
                ON CONFLICT (discord_channel_id) DO UPDATE SET
                    discord_user_id = EXCLUDED.discord_user_id,
                    device_code = EXCLUDED.device_code,
                    user_code = EXCLUDED.user_code,
                    verification_uri = EXCLUDED.verification_uri,
                    interval_seconds = EXCLUDED.interval_seconds,
                    expires_at = EXCLUDED.expires_at,
                    scope = EXCLUDED.scope,
                    status = 'pending',
                    last_error = NULL,
                    last_polled_at = NULL,
                    updated_at = NOW()
                RETURNING discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                          expires_at, scope, status, last_error, last_polled_at
                """,
                (
                    flow.discord_channel_id,
                    flow.discord_user_id,
                    flow.device_code,
                    flow.user_code,
                    flow.verification_uri,
                    flow.interval_seconds,
                    flow.expires_at,
                    Jsonb(list(flow.scope)),
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_device_flow.upsert_pending_flow")
        return self._build_record(row)

    async def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:
        """Return every device-code flow still waiting for authorization."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE status = 'pending'
                ORDER BY discord_channel_id
                """
            )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def mark_failed(self, *, discord_channel_id: int, last_error: str) -> TwitchDeviceFlowRecord | None:
        """Mark one device-code flow as failed with its final error."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE twitch_device_flow
                SET status = 'failed',
                    last_error = %s,
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                RETURNING discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                          expires_at, scope, status, last_error, last_polled_at
                """,
                (last_error, discord_channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def touch_polled(self, *, discord_channel_id: int) -> None:
        """Update the last-polled timestamp for one device-code flow."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE twitch_device_flow
                SET last_polled_at = NOW(),
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                """,
                (discord_channel_id,),
            )

    async def update_interval(self, *, discord_channel_id: int, interval_seconds: int) -> None:
        """Store Twitch's latest requested polling interval."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                UPDATE twitch_device_flow
                SET interval_seconds = %s,
                    updated_at = NOW()
                WHERE discord_channel_id = %s
                """,
                (interval_seconds, discord_channel_id),
            )

    async def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:
        """Delete a device-code flow by Discord channel ID."""
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM twitch_device_flow
                WHERE discord_channel_id = %s
                RETURNING discord_channel_id
                """,
                (discord_channel_id,),
            )
            row = await cursor.fetchone()
        return row is not None

    async def get_by_discord_user_id(self, discord_user_id: int) -> TwitchDeviceFlowRecord | None:
        """Return the newest device-code flow for one Discord user."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_channel_id, discord_user_id, device_code, user_code, verification_uri, interval_seconds,
                       expires_at, scope, status, last_error, last_polled_at
                FROM twitch_device_flow
                WHERE discord_user_id = %s
                ORDER BY updated_at DESC, discord_channel_id DESC
                LIMIT 1
                """,
                (discord_user_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        """Delete the newest device-code flow for one Discord user."""
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return await self.remove_by_discord_channel_id(existing.discord_channel_id or 0)

    @staticmethod
    def _build_record(row: TwitchDeviceFlowRow) -> TwitchDeviceFlowRecord:
        return TwitchDeviceFlowRecord(
            discord_user_id=int(row[1]),
            discord_channel_id=int(row[0]) if row[0] is not None else None,
            device_code=row[2],
            user_code=row[3],
            verification_uri=row[4],
            interval_seconds=int(row[5]),
            expires_at=row[6].isoformat(),
            scope=tuple(row[7] or []),
            status=row[8],
            last_error=row[9],
            last_polled_at=row[10].isoformat() if row[10] is not None else None,
        )


@dataclass(slots=True)
class PostgresTwitchUserCacheRepository(TwitchUserCacheRepository):
    """Store and retrieve cached Twitch user metadata."""

    database: PostgresDatabase

    async def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:
        """Return cached Twitch metadata by Twitch user ID."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, chat_color, updated_at
                FROM twitch_user_cache
                WHERE twitch_user_id = %s
                """,
                (twitch_user_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:
        """Return cached Twitch metadata by normalized login."""
        normalized_login = twitch_login.strip().lower()
        if not normalized_login:
            return None
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, chat_color, updated_at
                FROM twitch_user_cache
                WHERE twitch_login = %s
                """,
                (normalized_login,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_record(row)

    async def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
        chat_color: str | None,
    ) -> TwitchUserCacheRecord:
        """Persist authoritative metadata fetched from Twitch APIs."""
        normalized_login = twitch_login.strip().lower()
        normalized_chat_color = self._normalize_chat_color(chat_color)
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM twitch_user_cache
                WHERE twitch_login = %s AND twitch_user_id <> %s
                """,
                (normalized_login, twitch_user_id),
            )
            await cursor.execute(
                """
                INSERT INTO twitch_user_cache (
                    twitch_user_id,
                    twitch_login,
                    display_name,
                    profile_image_url,
                    chat_color,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = EXCLUDED.display_name,
                    profile_image_url = EXCLUDED.profile_image_url,
                    chat_color = COALESCE(EXCLUDED.chat_color, twitch_user_cache.chat_color),
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR twitch_user_cache.display_name IS DISTINCT FROM EXCLUDED.display_name
                          OR twitch_user_cache.profile_image_url IS DISTINCT FROM EXCLUDED.profile_image_url
                          OR (
                              EXCLUDED.chat_color IS NOT NULL
                              AND twitch_user_cache.chat_color IS DISTINCT FROM EXCLUDED.chat_color
                          )
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, chat_color, updated_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    display_name,
                    profile_image_url,
                    normalized_chat_color,
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_user_cache.upsert_from_api")
        return self._build_record(row)

    async def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
        chat_color: str | None = None,
    ) -> TwitchUserCacheRecord:
        """Persist metadata observed cheaply from IRC chat tags."""
        normalized_login = twitch_login.strip().lower()
        normalized_display_name = (display_name or "").strip() or None
        normalized_chat_color = self._normalize_chat_color(chat_color)
        async with self.database.async_cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM twitch_user_cache
                WHERE twitch_login = %s AND twitch_user_id <> %s
                """,
                (normalized_login, twitch_user_id),
            )
            await cursor.execute(
                """
                INSERT INTO twitch_user_cache (
                    twitch_user_id,
                    twitch_login,
                    display_name,
                    profile_image_url,
                    chat_color,
                    updated_at
                )
                VALUES (%s, %s, %s, NULL, %s, NOW())
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = COALESCE(%s, twitch_user_cache.display_name, EXCLUDED.display_name),
                    chat_color = COALESCE(%s, twitch_user_cache.chat_color),
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR (%s::text IS NOT NULL AND twitch_user_cache.display_name IS DISTINCT FROM %s::text)
                          OR (%s::text IS NOT NULL AND twitch_user_cache.chat_color IS DISTINCT FROM %s::text)
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, chat_color, updated_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    normalized_display_name or normalized_login,
                    normalized_chat_color,
                    normalized_display_name,
                    normalized_chat_color,
                    normalized_display_name,
                    normalized_display_name,
                    normalized_chat_color,
                    normalized_chat_color,
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_user_cache.observe_from_chat")
        return self._build_record(row)

    async def list_all(self) -> list[TwitchUserCacheRecord]:
        """Return every persisted Twitch user cache record."""
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, chat_color, updated_at
                FROM twitch_user_cache
                ORDER BY twitch_user_id
                """
            )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def upsert_many_from_api(self, records: tuple[TwitchUserCacheUpsert, ...]) -> None:
        """Persist a deduplicated batch of Twitch API metadata."""
        if not records:
            return
        async with self.database.async_transaction() as connection, connection.cursor() as cursor:
            deduplicated = {}
            for twitch_user_id, twitch_login, display_name, profile_image_url, chat_color in records:
                deduplicated[twitch_user_id] = (
                    twitch_user_id,
                    twitch_login.strip().lower(),
                    display_name,
                    profile_image_url,
                    self._normalize_chat_color(chat_color),
                )
            normalized_records = tuple(deduplicated.values())
            await cursor.executemany(
                """
                DELETE FROM twitch_user_cache
                WHERE twitch_login = %s AND twitch_user_id <> %s
                """,
                [(twitch_login, twitch_user_id) for twitch_user_id, twitch_login, _, _, _ in normalized_records],
            )
            await cursor.executemany(
                """
                INSERT INTO twitch_user_cache (
                    twitch_user_id,
                    twitch_login,
                    display_name,
                    profile_image_url,
                    chat_color,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = EXCLUDED.display_name,
                    profile_image_url = EXCLUDED.profile_image_url,
                    chat_color = COALESCE(EXCLUDED.chat_color, twitch_user_cache.chat_color),
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR twitch_user_cache.display_name IS DISTINCT FROM EXCLUDED.display_name
                          OR twitch_user_cache.profile_image_url IS DISTINCT FROM EXCLUDED.profile_image_url
                          OR (
                              EXCLUDED.chat_color IS NOT NULL
                              AND twitch_user_cache.chat_color IS DISTINCT FROM EXCLUDED.chat_color
                          )
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END
                """,
                normalized_records,
            )

    @staticmethod
    def _build_record(row: TwitchUserCacheRow) -> TwitchUserCacheRecord:
        return TwitchUserCacheRecord(
            twitch_user_id=str(row[0]),
            twitch_login=row[1],
            display_name=row[2],
            profile_image_url=row[3],
            chat_color=row[4],
            updated_at=row[5].isoformat(),
        )

    @staticmethod
    def _normalize_chat_color(value: str | None) -> str | None:
        return None if value is None else value.strip()
