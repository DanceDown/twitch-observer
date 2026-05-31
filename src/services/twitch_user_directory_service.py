"""Persistent Twitch user metadata lookup cache backed by PostgreSQL."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import asyncio

from src.database.connection import TwitchUserCacheRecord, TwitchUserCacheRepository
from src.events.event_types import TwitchChatMessageEvent
from src.gateways.twitch_api import TwitchAPIClient, TwitchUser
from src.utils.async_utils import resolve_awaitable


def _record_to_twitch_user(record: TwitchUserCacheRecord) -> TwitchUser:
    return TwitchUser(
        user_id=record.twitch_user_id,
        login=record.twitch_login,
        display_name=record.display_name,
        profile_image_url=record.profile_image_url,
    )


@dataclass(slots=True)
class TwitchUserDirectoryService:
    """Resolve Twitch users and broadcasters through a persistent cache."""

    twitch_api: TwitchAPIClient
    repository: TwitchUserCacheRepository
    memory_cache_size: int
    api_refresh_interval_seconds: int
    channel_api_refresh_interval_seconds: int
    _users_by_id: OrderedDict[str, TwitchUserCacheRecord] = field(default_factory=OrderedDict, init=False)
    _user_ids_by_login: dict[str, str] = field(default_factory=dict, init=False)
    _inflight_by_user_id: dict[str, asyncio.Task[TwitchUser]] = field(default_factory=dict, init=False)
    _inflight_by_login: dict[str, asyncio.Task[TwitchUser]] = field(default_factory=dict, init=False)

    async def start(self) -> None:
        await self.twitch_api.start()

    async def close(self) -> None:
        await self.twitch_api.close()

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        normalized_login = login.strip().lower()
        if not normalized_login:
            return None
        cached = self._get_record_from_memory_by_login(normalized_login)
        return None if cached is None else _record_to_twitch_user(cached)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        cached = self._get_record_from_memory_by_id(normalized_user_id)
        return None if cached is None else _record_to_twitch_user(cached)

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        normalized_login = login.strip().lower()
        if not normalized_login:
            return None
        record = await self._get_or_load_record_by_login(normalized_login)
        return None if record is None else _record_to_twitch_user(record)

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        record = await self._get_or_load_record_by_id(normalized_user_id)
        return None if record is None else _record_to_twitch_user(record)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        normalized_login = login.strip().lower()
        if not normalized_login:
            return await self.refresh_user_by_login(login)
        cached = await self._get_or_load_record_by_login(normalized_login)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_login(login)

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        normalized_login = login.strip().lower()
        key = normalized_login or login
        return await self._run_singleflight_login(key, lambda: self._refresh_user_by_login_uncached(login))

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        """Refresh broadcaster metadata by login for channel-scoped commands."""
        return await self.refresh_user_by_login(login)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id(user_id)
        cached = await self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id(user_id)
        cached = await self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        key = normalized_user_id or user_id
        return await self._run_singleflight_user_id(key, lambda: self._refresh_user_by_id_uncached(user_id))

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        normalized_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
        if not normalized_ids:
            return ()
        users = await self.twitch_api.get_users_by_ids(normalized_ids)
        self._remember_api_users(users)
        return users

    async def list_cached_users(self) -> tuple[TwitchUserCacheRecord, ...]:
        records = await resolve_awaitable(self.repository.list_all())
        for record in records:
            self._remember_record(record)
        return tuple(records)

    def upsert_users_from_api(self, users: tuple[TwitchUser, ...]) -> None:
        records = tuple(
            (user.user_id, user.login, user.display_name, user.profile_image_url)
            for user in users
        )
        self.repository.upsert_many_from_api(records)
        self._remember_api_users(users)

    def observe_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Warm the cache from IRC metadata without touching the Twitch API."""
        if event.author_id:
            record = self.repository.observe_from_chat(
                twitch_user_id=event.author_id,
                twitch_login=event.author_login,
                display_name=event.author_display_name or event.author_login,
            )
            self._remember_record(record)
        if event.broadcaster_id:
            existing_broadcaster = self.get_cached_user_by_id(event.broadcaster_id)
            record = self.repository.observe_from_chat(
                twitch_user_id=event.broadcaster_id,
                twitch_login=event.channel_login,
                display_name=None if existing_broadcaster is None else existing_broadcaster.display_name,
            )
            self._remember_record(record)

    async def _get_or_load_record_by_login(self, login: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_login(login)
        if cached is not None:
            return cached
        record = await resolve_awaitable(self.repository.get_by_login(login))
        if record is None:
            return None
        self._remember_record(record)
        return record

    async def _get_or_load_record_by_id(self, user_id: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_id(user_id)
        if cached is not None:
            return cached
        record = await resolve_awaitable(self.repository.get_by_user_id(user_id))
        if record is None:
            return None
        self._remember_record(record)
        return record

    def _get_record_from_memory_by_login(self, login: str) -> TwitchUserCacheRecord | None:
        user_id = self._user_ids_by_login.get(login)
        if user_id is None:
            return None
        return self._get_record_from_memory_by_id(user_id)

    def _get_record_from_memory_by_id(self, user_id: str) -> TwitchUserCacheRecord | None:
        user = self._users_by_id.get(user_id)
        if user is None:
            return None
        self._users_by_id.move_to_end(user_id)
        return user

    def _remember_record(self, record: TwitchUserCacheRecord) -> None:
        previous = self._users_by_id.get(record.twitch_user_id)
        if previous is not None and previous.twitch_login != record.twitch_login:
            self._user_ids_by_login.pop(previous.twitch_login, None)
        self._users_by_id[record.twitch_user_id] = record
        self._users_by_id.move_to_end(record.twitch_user_id)
        self._user_ids_by_login[record.twitch_login] = record.twitch_user_id
        self._trim_memory_cache()

    def _remember_api_users(self, users: tuple[TwitchUser, ...]) -> None:
        for user in users:
            self._remember_record(
                TwitchUserCacheRecord(
                    twitch_user_id=user.user_id,
                    twitch_login=user.login,
                    display_name=user.display_name,
                    profile_image_url=user.profile_image_url,
                    updated_at="",
                    last_api_refresh_at="",
                )
            )

    def _trim_memory_cache(self) -> None:
        while len(self._users_by_id) > max(1, self.memory_cache_size):
            evicted_user_id, evicted_user = self._users_by_id.popitem(last=False)
            current_user_id = self._user_ids_by_login.get(evicted_user.twitch_login)
            if current_user_id == evicted_user_id:
                self._user_ids_by_login.pop(evicted_user.twitch_login, None)

    async def _refresh_user_by_login_uncached(self, login: str) -> TwitchUser:
        user = await self.twitch_api.get_user_by_login(login)
        record = self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
        )
        self._remember_record(record)
        return user

    async def _refresh_user_by_id_uncached(self, user_id: str) -> TwitchUser:
        user = await self.twitch_api.get_user_by_id(user_id)
        record = self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
        )
        self._remember_record(record)
        return user

    async def _run_singleflight_login(
        self,
        key: str,
        loader: Callable[[], Awaitable[TwitchUser]],
    ) -> TwitchUser:
        inflight = self._inflight_by_login.get(key)
        if inflight is not None:
            return await inflight
        task = asyncio.create_task(loader())
        self._inflight_by_login[key] = task
        try:
            return await task
        finally:
            if self._inflight_by_login.get(key) is task:
                self._inflight_by_login.pop(key, None)

    async def _run_singleflight_user_id(
        self,
        key: str,
        loader: Callable[[], Awaitable[TwitchUser]],
    ) -> TwitchUser:
        inflight = self._inflight_by_user_id.get(key)
        if inflight is not None:
            return await inflight
        task = asyncio.create_task(loader())
        self._inflight_by_user_id[key] = task
        try:
            return await task
        finally:
            if self._inflight_by_user_id.get(key) is task:
                self._inflight_by_user_id.pop(key, None)


@dataclass(slots=True)
class TwitchUserDirectoryIngestService:
    """Feed the persistent Twitch user cache from incoming IRC chat events."""

    directory: TwitchUserDirectoryService

    def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        self.directory.observe_chat_message(event)
