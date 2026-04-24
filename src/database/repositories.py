from __future__ import annotations

"""Repository interfaces for PostgreSQL-backed persistence."""

from datetime import datetime

from src.events.event_types import TwitchChatMessageEvent

from .records import (
    AdapterEventActionRecord,
    AdapterEventRecord,
    ChannelRecord,
    PatternRecord,
    RecentMessageRecord,
    ReplyRecord,
    ThreadRecord,
    TrackedChannelStateRecord,
    TrackedUserRecord,
    TwitchAccountRecord,
    TwitchDeviceFlowRecord,
    TwitchUserCacheRecord,
    UserPermissionRecord,
)


class MessageRepository:
    """Persistence interface for normalized Twitch chat messages."""

    def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_recent_messages(
        self,
        *,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:  # pragma: no cover - interface
        raise NotImplementedError


class ThreadRepository:
    """Persistence interface for Discord thread/channel configuration roots."""

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:  # pragma: no cover
        raise NotImplementedError

    def delete_by_discord_channel_id(
        self,
        discord_channel_id: int,
    ) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_enabled(
        self,
        *,
        discord_channel_id: int,
        enabled: bool,
    ) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_color(
        self,
        *,
        discord_channel_id: int,
        color: str | None,
    ) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_account_id(
        self,
        *,
        discord_channel_id: int,
        account_id: int | None,
    ) -> ThreadRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:  # pragma: no cover
        raise NotImplementedError


class TwitchAccountRepository:
    """Persistence interface for linked Twitch accounts."""

    def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:  # pragma: no cover
        raise NotImplementedError

    def create_account(
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
    ) -> TwitchAccountRecord:  # pragma: no cover
        raise NotImplementedError

    def update_account(
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
    ) -> TwitchAccountRecord | None:  # pragma: no cover
        raise NotImplementedError

    def remove_by_account_id(self, account_id: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_by_discord_user_id(
        self,
        discord_user_id: int,
    ) -> TwitchAccountRecord | None:  # pragma: no cover - compatibility
        raise NotImplementedError

    def upsert_account(
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
    ) -> TwitchAccountRecord:  # pragma: no cover - compatibility
        raise NotImplementedError

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover - compatibility
        raise NotImplementedError

    def list_accounts(self) -> list[TwitchAccountRecord]:  # pragma: no cover
        raise NotImplementedError


class TwitchDeviceFlowRepository:
    """Persistence interface for pending Twitch Device Code logins."""

    def get_by_discord_channel_id(
        self,
        discord_channel_id: int,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_pending_flow(
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
    ) -> TwitchDeviceFlowRecord:  # pragma: no cover
        raise NotImplementedError

    def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:  # pragma: no cover
        raise NotImplementedError

    def mark_failed(
        self,
        *,
        discord_channel_id: int,
        last_error: str,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        raise NotImplementedError

    def touch_polled(self, *, discord_channel_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def update_interval(
        self,
        *,
        discord_channel_id: int,
        interval_seconds: int,
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_by_discord_user_id(
        self,
        discord_user_id: int,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover - compatibility
        raise NotImplementedError

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover - compatibility
        raise NotImplementedError


class TwitchUserCacheRepository:
    """Persistence interface for Twitch user metadata cached by ID and login."""

    def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        raise NotImplementedError

    def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        raise NotImplementedError

    def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        raise NotImplementedError


class ChannelRepository:
    """Persistence interface for per-thread Twitch channel subscriptions."""

    def get_by_thread_and_twitch_channel(
        self,
        thread_id: int,
        twitch_channel_id: str,
    ) -> ChannelRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_color(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        color: str | None,
    ) -> ChannelRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:  # pragma: no cover
        raise NotImplementedError

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:  # pragma: no cover
        raise NotImplementedError

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:  # pragma: no cover
        raise NotImplementedError

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_all_twitch_channel_ids(self) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def list_distinct_channel_states(self) -> list[TrackedChannelStateRecord]:  # pragma: no cover
        raise NotImplementedError


class TrackedUserRepository:
    """Persistence interface for per-thread tracked Twitch users."""

    def get_by_thread_and_twitch_user(
        self,
        thread_id: int,
        twitch_user_id: str,
    ) -> TrackedUserRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:  # pragma: no cover
        raise NotImplementedError

    def count_pattern_scope_references(
        self,
        *,
        thread_id: int,
        twitch_user_id: str,
    ) -> int:  # pragma: no cover
        raise NotImplementedError


class PatternRepository:
    """Persistence interface for per-thread ping/regex definitions."""

    def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_pattern_disabled(
        self,
        *,
        thread_id: int,
        p_index: int,
        disabled: bool,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_pattern_priority(
        self,
        *,
        thread_id: int,
        p_index: int,
        priority: int,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def update_pattern(
        self,
        *,
        thread_id: int,
        p_index: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:  # pragma: no cover
        raise NotImplementedError

    def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        p_index: int,
    ) -> PatternRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:  # pragma: no cover
        raise NotImplementedError

    def count_channel_scope_references(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
    ) -> int:  # pragma: no cover
        raise NotImplementedError


class ReplyRepository:
    """Persistence interface for auto-replies attached to patterns."""

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def add_reply(
        self,
        *,
        thread_id: int,
        p_index: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_reply_disabled(
        self,
        *,
        thread_id: int,
        p_index: int,
        disabled: bool,
    ) -> ReplyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_replies_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[ReplyRecord]:  # pragma: no cover
        raise NotImplementedError

    def disable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        raise NotImplementedError

    def enable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        raise NotImplementedError


class AdapterEventRepository:
    """Persistence interface for external adapter event triggers."""

    def upsert_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord:  # pragma: no cover
        raise NotImplementedError

    def get_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_events_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_matching_events(
        self,
        *,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
        include_disabled: bool = False,
    ) -> list[AdapterEventRecord]:  # pragma: no cover
        raise NotImplementedError


class AdapterEventActionRepository:
    """Persistence interface for follow-up actions on external adapter events."""

    def upsert_action(
        self,
        *,
        event_id: int,
        action_type: str,
        message_template: str | None,
        reply_as_reply: bool,
    ) -> AdapterEventActionRecord:  # pragma: no cover
        raise NotImplementedError

    def get_action(
        self,
        *,
        event_id: int,
        action_type: str,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        raise NotImplementedError

    def remove_action(
        self,
        *,
        event_id: int,
        action_type: str,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        raise NotImplementedError

    def set_action_disabled(
        self,
        *,
        event_id: int,
        action_type: str,
        disabled: bool,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_actions_for_event(
        self,
        event_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventActionRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_actions_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:  # pragma: no cover
        raise NotImplementedError


class UserPermissionRepository:
    """Persistence interface for additional per-thread Discord permissions."""

    def get_by_user_and_thread(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
    ) -> UserPermissionRecord | None:  # pragma: no cover
        raise NotImplementedError

    def upsert_permissions(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
        permissions: int,
    ) -> UserPermissionRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_by_user_and_thread(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:  # pragma: no cover
        raise NotImplementedError
