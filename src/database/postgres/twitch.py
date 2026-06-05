"""PostgreSQL repositories for Twitch account and cache state."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg.types.json import Jsonb

from ..records import TwitchAccountRecord, TwitchDeviceFlowRecord, TwitchUserCacheRecord
from ..repositories import TwitchAccountRepository, TwitchDeviceFlowRepository, TwitchUserCacheRepository
from ._utils import require_row, require_value
from .database import PostgresDatabase


@dataclass(slots=True)
class PostgresTwitchAccountRepository(TwitchAccountRepository):
    """Store and retrieve linked Twitch user accounts."""

    database: PostgresDatabase

    async def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
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

    async def create_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
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
                    discord_user_id,
                    twitch_user_id,
                    twitch_login,
                    client_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    Jsonb(list(scope)),
                    token_type,
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_account.create_account")
        return self._build_account_record(row)

    async def update_account(
        self,
        *,
        account_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord | None:
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
                    twitch_user_id,
                    twitch_login,
                    client_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    Jsonb(list(scope)),
                    token_type,
                    account_id,
                ),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._build_account_record(row)

    async def remove_by_account_id(self, account_id: int) -> bool:
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

    async def upsert_account(
        self,
        *,
        discord_user_id: int,
        twitch_user_id: str,
        twitch_login: str,
        client_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: str | None,
        scope: tuple[str, ...],
        token_type: str | None,
    ) -> TwitchAccountRecord:
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return await self.create_account(
                discord_user_id=discord_user_id,
                twitch_user_id=twitch_user_id,
                twitch_login=twitch_login,
                client_id=client_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
                token_type=token_type,
            )
        updated = await self.update_account(
            account_id=existing.account_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        return require_value(updated, operation="twitch_account.upsert_account")

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return await self.remove_by_account_id(existing.account_id)

    async def list_accounts(self) -> list[TwitchAccountRecord]:
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
    def _build_account_record(row: tuple) -> TwitchAccountRecord:
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

    async def upsert_pending_flow(
        self,
        *,
        discord_user_id: int,
        discord_channel_id: int,
        device_code: str,
        user_code: str,
        verification_uri: str,
        interval_seconds: int,
        expires_at: str,
        scope: tuple[str, ...],
    ) -> TwitchDeviceFlowRecord:
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
                    discord_channel_id,
                    discord_user_id,
                    device_code,
                    user_code,
                    verification_uri,
                    interval_seconds,
                    expires_at,
                    Jsonb(list(scope)),
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_device_flow.upsert_pending_flow")
        return self._build_record(row)

    async def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:
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
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return await self.remove_by_discord_channel_id(existing.discord_channel_id or 0)

    @staticmethod
    def _build_record(row: tuple) -> TwitchDeviceFlowRecord:
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
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
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
        normalized_login = twitch_login.strip().lower()
        if not normalized_login:
            return None
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
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
    ) -> TwitchUserCacheRecord:
        normalized_login = twitch_login.strip().lower()
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
                    updated_at,
                    last_api_refresh_at
                )
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = EXCLUDED.display_name,
                    profile_image_url = EXCLUDED.profile_image_url,
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR twitch_user_cache.display_name IS DISTINCT FROM EXCLUDED.display_name
                          OR twitch_user_cache.profile_image_url IS DISTINCT FROM EXCLUDED.profile_image_url
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END,
                    last_api_refresh_at = NOW()
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    display_name,
                    profile_image_url,
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
    ) -> TwitchUserCacheRecord:
        normalized_login = twitch_login.strip().lower()
        normalized_display_name = (display_name or "").strip() or None
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
                    updated_at,
                    last_api_refresh_at
                )
                VALUES (%s, %s, %s, NULL, NOW(), NULL)
                ON CONFLICT (twitch_user_id)
                DO UPDATE SET
                    twitch_login = EXCLUDED.twitch_login,
                    display_name = COALESCE(%s, twitch_user_cache.display_name, EXCLUDED.display_name),
                    updated_at = CASE
                        WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                          OR (%s::text IS NOT NULL AND twitch_user_cache.display_name IS DISTINCT FROM %s::text)
                        THEN NOW()
                        ELSE twitch_user_cache.updated_at
                    END
                RETURNING twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                """,
                (
                    twitch_user_id,
                    normalized_login,
                    normalized_display_name or normalized_login,
                    normalized_display_name,
                    normalized_display_name,
                    normalized_display_name,
                ),
            )
            row = await cursor.fetchone()
        row = require_row(row, operation="twitch_user_cache.observe_from_chat")
        return self._build_record(row)

    async def list_all(self) -> list[TwitchUserCacheRecord]:
        async with self.database.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT twitch_user_id, twitch_login, display_name, profile_image_url, updated_at, last_api_refresh_at
                FROM twitch_user_cache
                ORDER BY twitch_user_id
                """
            )
            rows = await cursor.fetchall()
        return [self._build_record(row) for row in rows]

    async def upsert_many_from_api(self, records: tuple[tuple[str, str, str, str | None], ...]) -> None:
        if not records:
            return
        async with self.database.async_transaction() as connection:
            async with connection.cursor() as cursor:
                deduplicated = {}
                for twitch_user_id, twitch_login, display_name, profile_image_url in records:
                    deduplicated[twitch_user_id] = (
                        twitch_user_id,
                        twitch_login.strip().lower(),
                        display_name,
                        profile_image_url,
                    )
                normalized_records = tuple(deduplicated.values())
                await cursor.executemany(
                    """
                    DELETE FROM twitch_user_cache
                    WHERE twitch_login = %s AND twitch_user_id <> %s
                    """,
                    [(twitch_login, twitch_user_id) for twitch_user_id, twitch_login, _, _ in normalized_records],
                )
                await cursor.executemany(
                    """
                    INSERT INTO twitch_user_cache (
                        twitch_user_id,
                        twitch_login,
                        display_name,
                        profile_image_url,
                        updated_at,
                        last_api_refresh_at
                    )
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (twitch_user_id)
                    DO UPDATE SET
                        twitch_login = EXCLUDED.twitch_login,
                        display_name = EXCLUDED.display_name,
                        profile_image_url = EXCLUDED.profile_image_url,
                        updated_at = CASE
                            WHEN twitch_user_cache.twitch_login IS DISTINCT FROM EXCLUDED.twitch_login
                              OR twitch_user_cache.display_name IS DISTINCT FROM EXCLUDED.display_name
                              OR twitch_user_cache.profile_image_url IS DISTINCT FROM EXCLUDED.profile_image_url
                            THEN NOW()
                            ELSE twitch_user_cache.updated_at
                        END,
                        last_api_refresh_at = NOW()
                    """,
                    normalized_records,
                )

    @staticmethod
    def _build_record(row: tuple) -> TwitchUserCacheRecord:
        return TwitchUserCacheRecord(
            twitch_user_id=str(row[0]),
            twitch_login=row[1],
            display_name=row[2],
            profile_image_url=row[3],
            updated_at=row[4].isoformat(),
            last_api_refresh_at=row[5].isoformat() if row[5] is not None else None,
        )
