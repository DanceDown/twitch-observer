from __future__ import annotations

"""Persistent Twitch user metadata cache backed by PostgreSQL."""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchDeviceCodeStart,
    TwitchDevicePollResult,
    TwitchUser,
    TwitchUserTokenBundle,
    TwitchValidatedToken,
)
from src.database.connection import TwitchUserCacheRecord, TwitchUserCacheRepository
from src.events.event_bus import EventBus
from src.events.event_types import EventType, TwitchChatMessageEvent


def _record_to_twitch_user(record: TwitchUserCacheRecord) -> TwitchUser:
    return TwitchUser(
        user_id=record.twitch_user_id,
        login=record.twitch_login,
        display_name=record.display_name,
        profile_image_url=record.profile_image_url,
    )


@dataclass(slots=True)
class TwitchUserDirectoryService:
    """Resolve Twitch users through a persistent cache with Helix fallback."""

    twitch_api: TwitchAPIClient
    repository: TwitchUserCacheRepository
    memory_cache_size: int
    api_refresh_interval_seconds: int
    _users_by_id: OrderedDict[str, TwitchUserCacheRecord] = field(default_factory=OrderedDict, init=False)
    _user_ids_by_login: dict[str, str] = field(default_factory=dict, init=False)

    async def start(self) -> None:
        await self.twitch_api.start()

    async def close(self) -> None:
        await self.twitch_api.close()

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        normalized_login = login.strip().lower()
        if not normalized_login:
            return None
        cached = self._get_record_from_memory_by_login(normalized_login)
        if cached is not None:
            return _record_to_twitch_user(cached)
        record = self.repository.get_by_login(normalized_login)
        if record is None:
            return None
        self._remember_record(record)
        return _record_to_twitch_user(record)

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        cached = self._get_record_from_memory_by_id(normalized_user_id)
        if cached is not None:
            return _record_to_twitch_user(cached)
        record = self.repository.get_by_user_id(normalized_user_id)
        if record is None:
            return None
        self._remember_record(record)
        return _record_to_twitch_user(record)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        normalized_login = login.strip().lower()
        if not normalized_login:
            return await self.refresh_user_by_login(login)
        cached = self._get_or_load_record_by_login(normalized_login)
        if cached is not None:
            if self._should_refresh_from_api(cached):
                try:
                    return await self.refresh_user_by_login(normalized_login)
                except Exception:
                    return _record_to_twitch_user(cached)
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_login(login)

    async def refresh_user_by_login(self, login: str) -> TwitchUser:
        user = await self.twitch_api.get_user_by_login(login)
        record = self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
        )
        self._remember_record(record)
        return user

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return await self.refresh_user_by_id(user_id)
        cached = self._get_or_load_record_by_id(normalized_user_id)
        if cached is not None:
            if self._should_refresh_from_api(cached):
                try:
                    return await self.refresh_user_by_id(normalized_user_id)
                except Exception:
                    return _record_to_twitch_user(cached)
            return _record_to_twitch_user(cached)
        return await self.refresh_user_by_id(user_id)

    async def refresh_user_by_id(self, user_id: str) -> TwitchUser:
        user = await self.twitch_api.get_user_by_id(user_id)
        record = self.repository.upsert_from_api(
            twitch_user_id=user.user_id,
            twitch_login=user.login,
            display_name=user.display_name,
            profile_image_url=user.profile_image_url,
        )
        self._remember_record(record)
        return user

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

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        return await self.twitch_api.validate_user_access_token(access_token)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        return await self.twitch_api.start_device_code_flow(scopes=scopes)

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        return await self.twitch_api.poll_device_code_flow(device_code=device_code, scopes=scopes)

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        return await self.twitch_api.refresh_user_access_token(refresh_token)

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str:
        return await self.twitch_api.send_chat_message(
            access_token=access_token,
            client_id=client_id,
            sender_id=sender_id,
            broadcaster_id=broadcaster_id,
            message=message,
            reply_parent_message_id=reply_parent_message_id,
        )

    def _get_or_load_record_by_login(self, login: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_login(login)
        if cached is not None:
            return cached
        record = self.repository.get_by_login(login)
        if record is None:
            return None
        self._remember_record(record)
        return record

    def _get_or_load_record_by_id(self, user_id: str) -> TwitchUserCacheRecord | None:
        cached = self._get_record_from_memory_by_id(user_id)
        if cached is not None:
            return cached
        record = self.repository.get_by_user_id(user_id)
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

    def _should_refresh_from_api(self, record: TwitchUserCacheRecord) -> bool:
        if not record.profile_image_url:
            return True
        if self.api_refresh_interval_seconds <= 0:
            return False
        if not record.last_api_refresh_at:
            return True
        try:
            last_refresh = datetime.fromisoformat(record.last_api_refresh_at)
        except ValueError:
            return True
        return datetime.now(timezone.utc) >= last_refresh + timedelta(seconds=self.api_refresh_interval_seconds)

    def _trim_memory_cache(self) -> None:
        while len(self._users_by_id) > max(1, self.memory_cache_size):
            evicted_user_id, evicted_user = self._users_by_id.popitem(last=False)
            current_user_id = self._user_ids_by_login.get(evicted_user.twitch_login)
            if current_user_id == evicted_user_id:
                self._user_ids_by_login.pop(evicted_user.twitch_login, None)


@dataclass(slots=True)
class TwitchUserDirectoryIngestService:
    """Feed the persistent Twitch user cache from incoming IRC chat events."""

    event_bus: EventBus
    directory: TwitchUserDirectoryService

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, self.handle_chat_message)

    def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        self.directory.observe_chat_message(event)
