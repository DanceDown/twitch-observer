"""Persistent Twitch user metadata lookup cache backed by PostgreSQL."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from src.database.connection import TwitchUserCacheRecord, TwitchUserCacheRepository
from src.events.twitch_events import TwitchChatMessageEvent
from src.gateways.twitch_api import TwitchAPIClient, TwitchUser


def _record_to_twitch_user(record: TwitchUserCacheRecord) -> TwitchUser:
    return TwitchUser(
        user_id=record.twitch_user_id,
        login=record.twitch_login,
        display_name=record.display_name,
        profile_image_url=record.profile_image_url,
        chat_color=record.chat_color,
    )


@dataclass(slots=True)
class TwitchUserDirectoryService:
    """Resolve Twitch users and broadcasters through memory, PostgreSQL, and Helix."""

    twitch_api: TwitchAPIClient
    repository: TwitchUserCacheRepository
    memory_cache_size: int
    _users_by_id: OrderedDict[str, TwitchUserCacheRecord] = field(default_factory=OrderedDict, init=False)
    _user_ids_by_login: dict[str, str] = field(default_factory=dict, init=False)
    _inflight_by_user_id: dict[str, asyncio.Task[TwitchUser]] = field(default_factory=dict, init=False)
    _inflight_by_login: dict[str, asyncio.Task[TwitchUser]] = field(default_factory=dict, init=False)

    async def start(self) -> None:
        """Open the underlying Twitch API session."""
        await self.twitch_api.start()

    async def close(self) -> None:
        """Close the underlying Twitch API session."""
        await self._cancel_inflight_refreshes()
        await self.twitch_api.close()

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Return an in-memory cached user by login without any I/O."""
        normalized_login = login.strip().lower()
        if not normalized_login:
            return None
        cached = self._get_record_from_memory_by_login(normalized_login)
        return None if cached is None else _record_to_twitch_user(cached)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Return an in-memory cached user by Twitch ID without any I/O."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        cached = self._get_record_from_memory_by_id(normalized_user_id)
        return None if cached is None else _record_to_twitch_user(cached)

    async def load_cached_user_by_login(self, login: str) -> TwitchUser | None:
        """Return a cached user by login, loading PostgreSQL when memory misses."""
        normalized_login = login.strip().lower()
        if not normalized_login:
            return None
        record = await self._get_or_load_record_by_login(normalized_login)
        return None if record is None else _record_to_twitch_user(record)

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        """Return a cached user by Twitch ID, loading PostgreSQL when memory misses."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        record = await self._get_or_load_record_by_id(normalized_user_id)
        return None if record is None else _record_to_twitch_user(record)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        """Resolve a user by login, preferring cache and refreshing on misses."""
        normalized_login = login.strip().lower()
        if not normalized_login:
            return await self.refresh_user_by_login(login)
        cached = await self._get_or_load_record_by_login(normalized_login)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_login(login)

    async def get_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Resolve a user by login and refresh when the cached chat color is unknown."""
        normalized_login = login.strip().lower()
        if not normalized_login:
            return await self.refresh_user_by_login_with_chat_color(login)
        cached = await self._get_or_load_record_by_login(normalized_login)
        if cached is not None and cached.chat_color is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_login_with_chat_color(login)

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        """Refresh a login through Helix with singleflight de-duplication."""
        normalized_login = login.strip().lower()
        key = normalized_login or login
        return await self._run_singleflight_login(key, lambda: self._refresh_user_by_login_uncached(login, include_chat_color=False))

    async def refresh_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Refresh a login through Helix and include Twitch chat-name color."""
        normalized_login = login.strip().lower()
        key = f"{normalized_login or login}:chat-color"
        return await self._run_singleflight_login(key, lambda: self._refresh_user_by_login_uncached(login, include_chat_color=True))

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        """Refresh broadcaster metadata by login for channel-scoped commands."""
        return await self.refresh_user_by_login(login)

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        """Resolve a user by Twitch ID, preferring cache and refreshing on misses."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id(user_id)
        cached = await self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id(user_id)

    async def get_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Resolve a user by Twitch ID and refresh when the cached chat color is unknown."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id_with_chat_color(user_id)
        cached = await self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None and cached.chat_color is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id_with_chat_color(user_id)

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        """Resolve broadcaster metadata by Twitch ID through the same user cache."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id(user_id)
        cached = await self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None:
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        """Refresh a Twitch ID through Helix with singleflight de-duplication."""
        normalized_user_id = user_id.strip()
        key = normalized_user_id or user_id
        return await self._run_singleflight_user_id(key, lambda: self._refresh_user_by_id_uncached(user_id, include_chat_color=False))

    async def refresh_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Refresh a Twitch ID through Helix and include Twitch chat-name color."""
        normalized_user_id = user_id.strip()
        key = f"{normalized_user_id or user_id}:chat-color"
        return await self._run_singleflight_user_id(key, lambda: self._refresh_user_by_id_uncached(user_id, include_chat_color=True))

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Resolve many users directly through Helix and warm the memory cache."""
        normalized_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
        if not normalized_ids:
            return ()
        users = await self.twitch_api.get_users_by_ids(normalized_ids)
        self._remember_api_users(users)
        return users

    async def get_users_by_ids_with_chat_colors(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Resolve many users through Helix including Twitch chat-name colors."""
        normalized_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
        if not normalized_ids:
            return ()
        users = await self.twitch_api.get_users_by_ids_with_chat_colors(normalized_ids)
        self._remember_api_users(users)
        return users

    async def list_cached_users(self) -> tuple[TwitchUserCacheRecord, ...]:
        """Load all persisted cache rows and mirror them into memory."""
        records = await self.repository.list_all()
        for record in records:
            self._remember_record(record)
        return tuple(records)

    async def upsert_users_from_api(self, users: tuple[TwitchUser, ...]) -> None:
        """Persist API-fresh users in one batch and mirror them into memory."""
        records = tuple((user.user_id, user.login, user.display_name, user.profile_image_url, user.chat_color) for user in users)
        await self.repository.upsert_many_from_api(records)
        self._remember_api_users(users)

    async def observe_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Warm the cache from IRC metadata without touching the Twitch API."""
        if event.author_id:
            await self._observe_chat_identity(
                twitch_user_id=event.author_id,
                twitch_login=event.author_login,
                display_name=event.author_display_name or event.author_login,
                chat_color=event.color,
            )
        if event.broadcaster_id:
            existing_broadcaster = self.get_cached_user_by_id(event.broadcaster_id)
            await self._observe_chat_identity(
                twitch_user_id=event.broadcaster_id,
                twitch_login=event.channel_login,
                display_name=None if existing_broadcaster is None else existing_broadcaster.display_name,
                chat_color=event.color if event.author_id == event.broadcaster_id else None,
            )

    async def _observe_chat_identity(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
        chat_color: str | None,
    ) -> None:
        cached = self._get_record_from_memory_by_id(twitch_user_id.strip())
        if cached is not None and self._chat_identity_matches(
            cached,
            twitch_login=twitch_login,
            display_name=display_name,
            chat_color=chat_color,
        ):
            return
        record = await self.repository.observe_from_chat(
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            display_name=display_name,
            chat_color=chat_color,
        )
        self._remember_record(record)

    @staticmethod
    def _chat_identity_matches(
        record: TwitchUserCacheRecord,
        *,
        twitch_login: str,
        display_name: str | None,
        chat_color: str | None,
    ) -> bool:
        if record.twitch_login != twitch_login.strip().lower():
            return False
        if display_name is None:
            return chat_color is None or record.chat_color == chat_color
        return record.display_name == display_name.strip() and (chat_color is None or record.chat_color == chat_color)

    async def _get_or_load_record_by_login(self, login: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_login(login)
        if cached is not None:
            return cached
        record = await self.repository.get_by_login(login)
        if record is None:
            return None
        self._remember_record(record)
        return record

    async def _get_or_load_record_by_id(self, user_id: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_id(user_id)
        if cached is not None:
            return cached
        record = await self.repository.get_by_user_id(user_id)
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
                    chat_color=user.chat_color,
                    updated_at="",
                )
            )

    def _trim_memory_cache(self) -> None:
        while len(self._users_by_id) > max(1, self.memory_cache_size):
            evicted_user_id, evicted_user = self._users_by_id.popitem(last=False)
            current_user_id = self._user_ids_by_login.get(evicted_user.twitch_login)
            if current_user_id == evicted_user_id:
                self._user_ids_by_login.pop(evicted_user.twitch_login, None)

    async def _refresh_user_by_login_uncached(self, login: str, *, include_chat_color: bool) -> TwitchUser:
        if include_chat_color:
            user = await self.twitch_api.get_user_by_login_with_chat_color(login)
        else:
            user = await self.twitch_api.get_user_by_login(login)
        record = await self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
            chat_color=user.chat_color,
        )

        self._remember_record(record)
        return user

    async def _refresh_user_by_id_uncached(self, user_id: str, *, include_chat_color: bool) -> TwitchUser:
        if include_chat_color:
            user = await self.twitch_api.get_user_by_id_with_chat_color(user_id)
        else:
            user = await self.twitch_api.get_user_by_id(user_id)
        record = await self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
            chat_color=user.chat_color,
        )

        self._remember_record(record)
        return user

    async def _run_singleflight_login(
        self,
        key: str,
        loader: Callable[[], Awaitable[TwitchUser]],
    ) -> TwitchUser:
        """Share one login refresh task across concurrent callers."""
        inflight = self._inflight_by_login.get(key)
        if inflight is not None:
            return await asyncio.shield(inflight)
        task = asyncio.create_task(loader())
        self._inflight_by_login[key] = task
        task.add_done_callback(lambda done: self._forget_login_task(key, done))
        return await asyncio.shield(task)

    async def _run_singleflight_user_id(
        self,
        key: str,
        loader: Callable[[], Awaitable[TwitchUser]],
    ) -> TwitchUser:
        """Share one ID refresh task across concurrent callers."""
        inflight = self._inflight_by_user_id.get(key)
        if inflight is not None:
            return await asyncio.shield(inflight)
        task = asyncio.create_task(loader())
        self._inflight_by_user_id[key] = task
        task.add_done_callback(lambda done: self._forget_user_id_task(key, done))
        return await asyncio.shield(task)

    def _forget_login_task(self, key: str, task: asyncio.Task[TwitchUser]) -> None:
        if self._inflight_by_login.get(key) is task:
            self._inflight_by_login.pop(key, None)
        with suppress(asyncio.CancelledError, Exception):
            task.exception()

    def _forget_user_id_task(self, key: str, task: asyncio.Task[TwitchUser]) -> None:
        if self._inflight_by_user_id.get(key) is task:
            self._inflight_by_user_id.pop(key, None)
        with suppress(asyncio.CancelledError, Exception):
            task.exception()

    async def _cancel_inflight_refreshes(self) -> None:
        tasks = tuple({*self._inflight_by_login.values(), *self._inflight_by_user_id.values()})
        self._inflight_by_login.clear()
        self._inflight_by_user_id.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


@dataclass(slots=True)
class TwitchUserDirectoryIngestService:
    """Feed the persistent Twitch user cache from incoming IRC chat events."""

    directory: TwitchUserDirectoryService

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Observe IRC metadata from one chat message."""
        await self.directory.observe_chat_message(event)
