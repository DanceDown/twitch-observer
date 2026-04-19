from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from src.adapters.discord import dispatch_account_command, dispatch_reply_command, dispatch_show_command
from src.adapters.twitch_api import (
    TwitchDeviceCodeStart,
    TwitchDevicePollResult,
    TwitchUser,
    TwitchUserTokenBundle,
    TwitchValidatedToken,
)
from src.database.connection import (
    ChannelRecord,
    ChannelEventReplyRecord,
    ChannelEventReplyRepository,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
    TwitchDeviceFlowRecord,
    TwitchDeviceFlowRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    EventType,
    TwitchChannelLiveStateChangedEvent,
    TwitchChatMessageEvent,
)
from src.services.account_service import AccountCommandService, AccountNotificationSender, DeviceFlowPollingService
from src.services.pattern_service import ShowCommandService
from src.services.reply_service import AutoReplyService, ChannelEventAutoReplyService, ReplyCommandService


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)
    next_thread_id: int = 1

    def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        for thread in self.threads_by_channel_id.values():
            if thread.thread_id == thread_id:
                return thread
        return None

    def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        thread = ThreadRecord(
            thread_id=self.next_thread_id,
            owner_id=owner_id,
            discord_channel_id=discord_channel_id,
            enabled=True,
            color=None,
            account_id=None,
        )
        self.next_thread_id += 1
        self.threads_by_channel_id[discord_channel_id] = thread
        return thread

    def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.pop(discord_channel_id, None)

    def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=enabled,
            color=thread.color,
            account_id=thread.account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=color,
            account_id=thread.account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    def set_account_id(self, *, discord_channel_id: int, account_id: int | None) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=thread.color,
            account_id=account_id,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:
        return [thread for thread in self.threads_by_channel_id.values() if thread.owner_id == owner_id]


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels_by_thread: dict[tuple[int, str], ChannelRecord] = field(default_factory=dict)

    def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        return self.channels_by_thread.get((thread_id, twitch_channel_id))

    def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread[(thread_id, twitch_channel_id)] = ChannelRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            color=None,
        )

    def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread.pop((thread_id, twitch_channel_id), None)

    def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        key = (thread_id, twitch_channel_id)
        existing = self.channels_by_thread.get(key)
        if existing is None:
            return None
        updated = ChannelRecord(
            thread_id=existing.thread_id,
            twitch_channel_id=existing.twitch_channel_id,
            color=color,
            is_live=existing.is_live,
            last_live_status_at=existing.last_live_status_at,
        )
        self.channels_by_thread[key] = updated
        return updated

    def set_live_state_for_twitch_channel(self, *, twitch_channel_id: str, is_live: bool, changed_at: str | None) -> int:
        updated_rows = 0
        for key, existing in list(self.channels_by_thread.items()):
            if existing.twitch_channel_id != twitch_channel_id:
                continue
            self.channels_by_thread[key] = ChannelRecord(
                thread_id=existing.thread_id,
                twitch_channel_id=existing.twitch_channel_id,
                color=existing.color,
                is_live=is_live,
                last_live_status_at=changed_at,
            )
            updated_rows += 1
        return updated_rows

    def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return [record for record in self.channels_by_thread.values() if record.thread_id == thread_id]


@dataclass
class InMemoryPatternRepository(PatternRepository):
    patterns: list[PatternRecord] = field(default_factory=list)

    def find_exact_pattern(self, **kwargs) -> PatternRecord | None:  # pragma: no cover - unused here
        raise NotImplementedError

    def add_pattern(self, **kwargs) -> PatternRecord:  # pragma: no cover - unused here
        raise NotImplementedError

    def remove_pattern(self, *, thread_id: int, p_index: int) -> None:
        self.patterns = [
            pattern
            for pattern in self.patterns
            if not (pattern.thread_id == thread_id and pattern.p_index == p_index)
        ]

    def set_pattern_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    p_index=pattern.p_index,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=disabled,
                    notify=pattern.notify,
                    priority=pattern.priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    def set_pattern_priority(self, *, thread_id: int, p_index: int, priority: int) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    p_index=pattern.p_index,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=pattern.disabled,
                    notify=pattern.notify,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

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
    ) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                updated = PatternRecord(
                    thread_id=thread_id,
                    p_index=p_index,
                    regex=regex,
                    channel_scope_mode=channel_scope_mode,
                    channel_scope_ids=tuple(sorted(channel_scope_ids)),
                    user_scope_mode=user_scope_mode,
                    user_scope_ids=tuple(sorted(user_scope_ids)),
                    sub_state=sub_state,
                    offline_state=offline_state,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    color=color,
                    disabled=pattern.disabled,
                    notify=pattern.notify,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id and not pattern.disabled and pattern.notify]
        return sorted(rows, key=lambda pattern: (-pattern.priority, pattern.p_index))

    def get_pattern_by_id(self, *, thread_id: int, p_index: int) -> PatternRecord | None:
        for pattern in self.patterns:
            if pattern.thread_id == thread_id and pattern.p_index == p_index:
                return pattern
        return None

    def list_patterns_for_thread(self, thread_id: int, *, is_regex: bool | None = None) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id]
        if is_regex is not None:
            rows = [pattern for pattern in rows if pattern.is_regex == is_regex]
        return sorted(rows, key=lambda pattern: (-pattern.priority, pattern.p_index))

    def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return sum(
            1
            for pattern in self.patterns
            if pattern.thread_id == thread_id and twitch_channel_id in pattern.channel_scope_ids
        )


@dataclass
class InMemoryReplyRepository(ReplyRepository):
    replies_by_pattern: dict[tuple[int, int], ReplyRecord] = field(default_factory=dict)

    def get_by_pattern(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        return self.replies_by_pattern.get((thread_id, p_index))

    def add_reply(
        self,
        *,
        thread_id: int,
        p_index: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:
        key = (thread_id, p_index)
        if key in self.replies_by_pattern:
            return None
        reply = ReplyRecord(
            thread_id=thread_id,
            p_index=p_index,
            reply_message=reply_message,
            reply_as_reply=reply_as_reply,
            disabled=False,
        )
        self.replies_by_pattern[key] = reply
        return reply

    def remove_reply(self, *, thread_id: int, p_index: int) -> ReplyRecord | None:
        return self.replies_by_pattern.pop((thread_id, p_index), None)

    def set_reply_disabled(self, *, thread_id: int, p_index: int, disabled: bool) -> ReplyRecord | None:
        key = (thread_id, p_index)
        existing = self.replies_by_pattern.get(key)
        if existing is None:
            return None
        updated = ReplyRecord(
            thread_id=existing.thread_id,
            p_index=existing.p_index,
            reply_message=existing.reply_message,
            reply_as_reply=existing.reply_as_reply,
            disabled=disabled,
        )
        self.replies_by_pattern[key] = updated
        return updated

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        rows = [reply for reply in self.replies_by_pattern.values() if reply.thread_id == thread_id]
        if not include_disabled:
            rows = [reply for reply in rows if not reply.disabled]
        return sorted(rows, key=lambda reply: reply.p_index)

    def disable_replies_for_thread(self, thread_id: int) -> int:
        count = 0
        for key, reply in list(self.replies_by_pattern.items()):
            if reply.thread_id == thread_id and not reply.disabled:
                self.replies_by_pattern[key] = ReplyRecord(
                    thread_id=reply.thread_id,
                    p_index=reply.p_index,
                    reply_message=reply.reply_message,
                    reply_as_reply=reply.reply_as_reply,
                    disabled=True,
                )
                count += 1
        return count

    def enable_replies_for_thread(self, thread_id: int) -> int:
        count = 0
        for key, reply in list(self.replies_by_pattern.items()):
            if reply.thread_id == thread_id and reply.disabled:
                self.replies_by_pattern[key] = ReplyRecord(
                    thread_id=reply.thread_id,
                    p_index=reply.p_index,
                    reply_message=reply.reply_message,
                    reply_as_reply=reply.reply_as_reply,
                    disabled=False,
                )
                count += 1
        return count


@dataclass
class InMemoryChannelEventReplyRepository(ChannelEventReplyRepository):
    replies: dict[tuple[int, str, str], ChannelEventReplyRecord] = field(default_factory=dict)

    def get_by_channel_event(self, *, thread_id: int, twitch_channel_id: str, event_state: str) -> ChannelEventReplyRecord | None:
        return self.replies.get((thread_id, twitch_channel_id, event_state))

    def upsert_reply(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        reply_message: str,
    ) -> ChannelEventReplyRecord:
        record = ChannelEventReplyRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            event_state=event_state,
            reply_message=reply_message,
            disabled=False,
        )
        self.replies[(thread_id, twitch_channel_id, event_state)] = record
        return record

    def remove_reply(self, *, thread_id: int, twitch_channel_id: str, event_state: str) -> ChannelEventReplyRecord | None:
        return self.replies.pop((thread_id, twitch_channel_id, event_state), None)

    def set_reply_disabled(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        event_state: str,
        disabled: bool,
    ) -> ChannelEventReplyRecord | None:
        key = (thread_id, twitch_channel_id, event_state)
        existing = self.replies.get(key)
        if existing is None:
            return None
        updated = ChannelEventReplyRecord(
            thread_id=existing.thread_id,
            twitch_channel_id=existing.twitch_channel_id,
            event_state=existing.event_state,
            reply_message=existing.reply_message,
            disabled=disabled,
        )
        self.replies[key] = updated
        return updated

    def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ChannelEventReplyRecord]:
        rows = [reply for reply in self.replies.values() if reply.thread_id == thread_id]
        if not include_disabled:
            rows = [reply for reply in rows if not reply.disabled]
        return sorted(rows, key=lambda reply: (reply.event_state, reply.twitch_channel_id))

    def list_replies_for_channel_event(
        self,
        *,
        twitch_channel_id: str,
        event_state: str,
        include_disabled: bool = False,
    ) -> list[ChannelEventReplyRecord]:
        rows = [
            reply
            for reply in self.replies.values()
            if reply.twitch_channel_id == twitch_channel_id and reply.event_state == event_state
        ]
        if not include_disabled:
            rows = [reply for reply in rows if not reply.disabled]
        return sorted(rows, key=lambda reply: reply.thread_id)


@dataclass
class InMemoryAccountRepository(TwitchAccountRepository):
    accounts_by_account_id: dict[int, TwitchAccountRecord] = field(default_factory=dict)
    next_account_id: int = 1

    def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:
        return self.accounts_by_account_id.get(account_id)

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
    ) -> TwitchAccountRecord:
        account_id = self.next_account_id
        self.next_account_id += 1
        record = TwitchAccountRecord(
            account_id=account_id,
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
        self.accounts_by_account_id[account_id] = record
        return record

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
    ) -> TwitchAccountRecord | None:
        existing = self.accounts_by_account_id.get(account_id)
        if existing is None:
            return None
        updated = TwitchAccountRecord(
            account_id=account_id,
            discord_user_id=existing.discord_user_id,
            twitch_user_id=twitch_user_id,
            twitch_login=twitch_login,
            client_id=client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
            token_type=token_type,
        )
        self.accounts_by_account_id[account_id] = updated
        return updated

    def remove_by_account_id(self, account_id: int) -> bool:
        return self.accounts_by_account_id.pop(account_id, None) is not None

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchAccountRecord | None:
        matches = [account for account in self.accounts_by_account_id.values() if account.discord_user_id == discord_user_id]
        if not matches:
            return None
        return sorted(matches, key=lambda account: account.account_id)[-1]

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
    ) -> TwitchAccountRecord:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return self.create_account(
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
        updated = self.update_account(
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
        assert updated is not None
        return updated

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None:
            return False
        return self.remove_by_account_id(existing.account_id)


@dataclass
class InMemoryDeviceFlowRepository(TwitchDeviceFlowRepository):
    flows_by_discord_channel_id: dict[int, TwitchDeviceFlowRecord] = field(default_factory=dict)

    def get_by_discord_channel_id(self, discord_channel_id: int) -> TwitchDeviceFlowRecord | None:
        return self.flows_by_discord_channel_id.get(discord_channel_id)

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
    ) -> TwitchDeviceFlowRecord:
        record = TwitchDeviceFlowRecord(
            discord_user_id=discord_user_id,
            discord_channel_id=discord_channel_id,
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            interval_seconds=interval_seconds,
            expires_at=expires_at,
            scope=scope,
            status="pending",
            last_error=None,
            last_polled_at=None,
        )
        self.flows_by_discord_channel_id[discord_channel_id] = record
        return record

    def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:
        return [flow for flow in self.flows_by_discord_channel_id.values() if flow.status == "pending"]

    def mark_failed(self, *, discord_channel_id: int, last_error: str) -> TwitchDeviceFlowRecord | None:
        existing = self.flows_by_discord_channel_id.get(discord_channel_id)
        if existing is None:
            return None
        updated = TwitchDeviceFlowRecord(
            discord_user_id=existing.discord_user_id,
            discord_channel_id=existing.discord_channel_id,
            device_code=existing.device_code,
            user_code=existing.user_code,
            verification_uri=existing.verification_uri,
            interval_seconds=existing.interval_seconds,
            expires_at=existing.expires_at,
            scope=existing.scope,
            status="failed",
            last_error=last_error,
            last_polled_at=existing.last_polled_at,
        )
        self.flows_by_discord_channel_id[discord_channel_id] = updated
        return updated

    def touch_polled(self, *, discord_channel_id: int) -> None:
        existing = self.flows_by_discord_channel_id.get(discord_channel_id)
        if existing is None:
            return
        self.flows_by_discord_channel_id[discord_channel_id] = TwitchDeviceFlowRecord(
            discord_user_id=existing.discord_user_id,
            discord_channel_id=existing.discord_channel_id,
            device_code=existing.device_code,
            user_code=existing.user_code,
            verification_uri=existing.verification_uri,
            interval_seconds=existing.interval_seconds,
            expires_at=existing.expires_at,
            scope=existing.scope,
            status=existing.status,
            last_error=existing.last_error,
            last_polled_at=datetime.now(timezone.utc).isoformat(),
        )

    def update_interval(self, *, discord_channel_id: int, interval_seconds: int) -> None:
        existing = self.flows_by_discord_channel_id.get(discord_channel_id)
        if existing is None:
            return
        self.flows_by_discord_channel_id[discord_channel_id] = TwitchDeviceFlowRecord(
            discord_user_id=existing.discord_user_id,
            discord_channel_id=existing.discord_channel_id,
            device_code=existing.device_code,
            user_code=existing.user_code,
            verification_uri=existing.verification_uri,
            interval_seconds=interval_seconds,
            expires_at=existing.expires_at,
            scope=existing.scope,
            status=existing.status,
            last_error=existing.last_error,
            last_polled_at=existing.last_polled_at,
        )

    def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:
        return self.flows_by_discord_channel_id.pop(discord_channel_id, None) is not None

    def get_by_discord_user_id(self, discord_user_id: int) -> TwitchDeviceFlowRecord | None:
        matches = [flow for flow in self.flows_by_discord_channel_id.values() if flow.discord_user_id == discord_user_id]
        if not matches:
            return None
        return sorted(matches, key=lambda flow: flow.discord_channel_id or 0)[-1]

    def remove_by_discord_user_id(self, discord_user_id: int) -> bool:
        existing = self.get_by_discord_user_id(discord_user_id)
        if existing is None or existing.discord_channel_id is None:
            return False
        return self.remove_by_discord_channel_id(existing.discord_channel_id)


@dataclass
class FakeTwitchAPI:
    device_start: TwitchDeviceCodeStart | None = None
    poll_result: TwitchDevicePollResult | None = None
    validated_token: TwitchValidatedToken | None = None
    sent_messages: list[dict[str, str | None]] = field(default_factory=list)
    live_by_user_id: dict[str, bool] = field(default_factory=dict)
    users_by_id: dict[str, TwitchUser] = field(default_factory=dict)
    poll_requests: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    refreshed_tokens: list[str] = field(default_factory=list)

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        assert self.device_start is not None
        return self.device_start

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        self.poll_requests.append((device_code, scopes))
        assert self.poll_result is not None
        return self.poll_result

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        assert self.validated_token is not None
        return self.validated_token

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        self.refreshed_tokens.append(refresh_token)
        assert self.poll_result is not None
        assert self.poll_result.token_bundle is not None
        return self.poll_result.token_bundle

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
        self.sent_messages.append(
            {
                "access_token": access_token,
                "client_id": client_id,
                "sender_id": sender_id,
                "broadcaster_id": broadcaster_id,
                "message": message,
                "reply_parent_message_id": reply_parent_message_id,
            }
        )
        return "sent-1"

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        return self.users_by_id[user_id]

    async def is_user_live(self, user_id: str) -> bool:
        return self.live_by_user_id.get(user_id, False)


@dataclass
class FakeNotifier(AccountNotificationSender):
    sent: list[tuple[int, DiscordCommandResult]] = field(default_factory=list)
    tracking_embeds: list[tuple[int, object]] = field(default_factory=list)

    async def send_account_result(
        self,
        discord_user_id: int,
        discord_channel_id: int | None,
        result: DiscordCommandResult,
    ) -> None:
        self.sent.append((discord_user_id, result))

    async def send_tracking_embed(self, discord_channel_id: int, embed, *, channel_login: str | None = None) -> None:
        self.tracking_embeds.append((discord_channel_id, embed))


@pytest.mark.asyncio
async def test_account_link_command_starts_device_flow() -> None:
    bus = EventBus()
    account_repository = InMemoryAccountRepository()
    device_flow_repository = InMemoryDeviceFlowRepository()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    twitch_api = FakeTwitchAPI(
        device_start=TwitchDeviceCodeStart(
            device_code="device-123",
            user_code="ABCDEFGH",
            verification_uri="https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH",
            expires_in=1800,
            interval=5,
        )
    )
    AccountCommandService(
        event_bus=bus,
        account_repository=account_repository,
        device_flow_repository=device_flow_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_account_command(
        bus,
        requester_id=200,
        discord_channel_id=100,
        action="link",
    )

    assert result.title == "Finish Twitch Login"
    assert "User Code: `ABCDEFGH`" in result.message
    pending = device_flow_repository.get_by_discord_channel_id(100)
    assert pending is not None
    assert pending.discord_channel_id == 100
    assert pending.user_code == "ABCDEFGH"
    assert pending.status == "pending"


@pytest.mark.asyncio
async def test_account_show_reports_pending_device_flow() -> None:
    bus = EventBus()
    device_flow_repository = InMemoryDeviceFlowRepository()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    device_flow_repository.upsert_pending_flow(
        discord_user_id=200,
        discord_channel_id=100,
        device_code="device-123",
        user_code="ABCDEFGH",
        verification_uri="https://example.test/activate",
        interval_seconds=5,
        expires_at=datetime.now(timezone.utc).isoformat(),
        scope=("user:write:chat",),
    )
    AccountCommandService(
        event_bus=bus,
        account_repository=InMemoryAccountRepository(),
        device_flow_repository=device_flow_repository,
        thread_repository=thread_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
    )

    result = await dispatch_account_command(bus, requester_id=200, discord_channel_id=100, action="show")

    assert result.title == "Twitch Account Status"
    assert "Pending Device Login" in result.message
    assert "ABCDEFGH" in result.message


@pytest.mark.asyncio
async def test_device_flow_poller_links_account_after_successful_authorization() -> None:
    account_repository = InMemoryAccountRepository()
    device_flow_repository = InMemoryDeviceFlowRepository()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    device_flow_repository.upsert_pending_flow(
        discord_user_id=200,
        discord_channel_id=100,
        device_code="device-123",
        user_code="ABCDEFGH",
        verification_uri="https://example.test/activate",
        interval_seconds=5,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        scope=("user:write:chat",),
    )
    twitch_api = FakeTwitchAPI(
        poll_result=TwitchDevicePollResult(
            status="success",
            token_bundle=TwitchUserTokenBundle(
                access_token="access-123",
                refresh_token="refresh-123",
                expires_in=3600,
                scope=("user:write:chat",),
                token_type="bearer",
            ),
        ),
        validated_token=TwitchValidatedToken(
            client_id="client-123",
            login="dancedown",
            user_id="77",
            scopes=("user:write:chat",),
            expires_in=3600,
            token_type="bearer",
        ),
    )
    notifier = FakeNotifier()
    poller = DeviceFlowPollingService(
        device_flow_repository=device_flow_repository,
        account_repository=account_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=notifier,
    )

    await poller.poll_once()

    thread = thread_repository.get_by_discord_channel_id(100)
    assert thread is not None
    assert thread.account_id is not None
    stored = account_repository.get_by_account_id(thread.account_id)
    assert stored is not None
    assert stored.twitch_login == "dancedown"
    assert device_flow_repository.get_by_discord_channel_id(100) is None
    assert notifier.sent[0][1].title == "Twitch Account Linked"


@pytest.mark.asyncio
async def test_device_flow_poller_marks_failed_authorizations() -> None:
    account_repository = InMemoryAccountRepository()
    device_flow_repository = InMemoryDeviceFlowRepository()
    thread_repository = InMemoryThreadRepository()
    thread_repository.create(owner_id=200, discord_channel_id=100)
    device_flow_repository.upsert_pending_flow(
        discord_user_id=200,
        discord_channel_id=100,
        device_code="device-123",
        user_code="ABCDEFGH",
        verification_uri="https://example.test/activate",
        interval_seconds=5,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        scope=("user:write:chat",),
    )
    twitch_api = FakeTwitchAPI(
        poll_result=TwitchDevicePollResult(status="failed", error_message="access_denied"),
    )
    notifier = FakeNotifier()
    poller = DeviceFlowPollingService(
        device_flow_repository=device_flow_repository,
        account_repository=account_repository,
        thread_repository=thread_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=notifier,
    )

    await poller.poll_once()

    pending = device_flow_repository.get_by_discord_channel_id(100)
    assert pending is not None
    assert pending.status == "failed"
    assert pending.last_error == "access_denied"
    assert notifier.sent[0][1].title == "Twitch Login Failed"


@pytest.mark.asyncio
async def test_account_unlink_keeps_attached_auto_replies() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token="refresh-123",
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    AccountCommandService(
        event_bus=bus,
        account_repository=account_repository,
        device_flow_repository=InMemoryDeviceFlowRepository(),
        thread_repository=thread_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
    )

    result = await dispatch_account_command(bus, requester_id=200, discord_channel_id=100, action="unlink")

    assert result.title == "Account Unlinked"
    assert "Existing auto-replies were kept" in result.message
    reply = reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=1)
    assert reply is not None
    assert reply.disabled is False


@pytest.mark.asyncio
async def test_reply_add_requires_linked_account() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                reply_message=None,
                reply_as_reply=False,
                priority=0,
            )
        ]
    )
    ReplyCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
        account_repository=InMemoryAccountRepository(),
    )

    result = await dispatch_reply_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_id=1,
        message="Hi there",
        reply_as_reply=True,
    )

    assert result.title == "No Linked Account"
    assert result.ephemeral is True


@pytest.mark.asyncio
async def test_reply_add_updates_pattern_reply_fields() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                reply_message=None,
                reply_as_reply=False,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    ReplyCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
    )

    result = await dispatch_reply_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_id=1,
        message="Hi there",
        reply_as_reply=True,
    )

    assert result.title == "Auto-Reply Added"
    reply = reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=1)
    assert reply is not None
    assert reply.reply_message == "Hi there"
    assert reply.reply_as_reply is True


@pytest.mark.asyncio
async def test_reply_add_rejects_overwriting_existing_auto_reply() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Existing", reply_as_reply=False)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    ReplyCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
    )

    result = await dispatch_reply_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_id=1,
        message="New one",
        reply_as_reply=True,
    )

    assert result.title == "Reply Already Exists"
    reply = reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=1)
    assert reply is not None
    assert reply.reply_message == "Existing"


@pytest.mark.asyncio
async def test_reply_disable_marks_reply_as_disabled() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    ReplyCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
    )

    result = await dispatch_reply_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="disable",
        pattern_id=1,
        message=None,
        reply_as_reply=False,
    )

    assert result.title == "Auto-Reply Disabled"
    reply = reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=1)
    assert reply is not None
    assert reply.disabled is True


@pytest.mark.asyncio
async def test_reply_enable_marks_reply_as_enabled() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    reply_repository.set_reply_disabled(thread_id=thread.thread_id, p_index=1, disabled=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    ReplyCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
    )

    result = await dispatch_reply_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        action="enable",
        pattern_id=1,
        message=None,
        reply_as_reply=False,
    )

    assert result.title == "Auto-Reply Enabled"
    reply = reply_repository.get_by_pattern(thread_id=thread.thread_id, p_index=1)
    assert reply is not None
    assert reply.disabled is False


@pytest.mark.asyncio
async def test_show_auto_replies_lists_attached_replies() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    ShowCommandService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
    )

    result = await dispatch_show_command(
        bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("auto_replies",),
    )

    assert result.title == "Configuration Overview"
    assert "- `1`" in result.message
    assert "Trigger: ``hello``" in result.message
    assert "Reply: ``Hi there``" in result.message


@pytest.mark.asyncio
async def test_auto_reply_service_sends_reply_for_matching_pattern() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(
        thread_id=thread.thread_id,
        p_index=1,
        reply_message="Hi {NAME}, you wrote `{MESSAGE}` in {CHANNEL}",
        reply_as_reply=True,
    )
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    notifier = FakeNotifier()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 1
    assert len(twitch_api.sent_messages) == 1
    assert twitch_api.sent_messages[0]["message"] == "Hi Alice, you wrote `hello there` in example"
    assert twitch_api.sent_messages[0]["reply_parent_message_id"] == "msg-1"
    assert len(notifier.tracking_embeds) == 1


@pytest.mark.asyncio
async def test_auto_reply_service_skips_self_reply_loops() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="7",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=FakeNotifier(),
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="dancedown",
            author_display_name="DanceDown",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 0
    assert twitch_api.sent_messages == []


@pytest.mark.asyncio
async def test_auto_reply_service_allows_self_reply_when_user_scope_is_only_selected() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="only_selected",
                user_scope_ids=("7",),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="7",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=FakeNotifier(),
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="dancedown",
            author_display_name="DanceDown",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 1
    assert len(twitch_api.sent_messages) == 1


@pytest.mark.asyncio
async def test_auto_reply_service_skips_disabled_thread() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    thread_repository.set_enabled(discord_channel_id=100, enabled=False)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=FakeNotifier(),
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 0
    assert twitch_api.sent_messages == []


@pytest.mark.asyncio
async def test_auto_reply_service_stops_after_first_matching_pattern_without_reply() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello there",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=9,
            ),
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=2,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=1,
            ),
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=2, reply_message="fallback", reply_as_reply=True)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=FakeNotifier(),
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there everyone",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 0
    assert twitch_api.sent_messages == []


@pytest.mark.asyncio
async def test_auto_reply_service_uses_persisted_channel_live_state_without_live_api_calls() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    channel_repository.set_live_state_for_twitch_channel(twitch_channel_id="42", is_live=True, changed_at="now")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                p_index=1,
                regex="hello",
                channel_scope_mode="all_tracked",
                channel_scope_ids=(),
                user_scope_mode="all_users",
                user_scope_ids=(),
                sub_state="all",
                offline_state="online",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                notify=True,
                priority=0,
            )
        ]
    )
    reply_repository = InMemoryReplyRepository()
    reply_repository.add_reply(thread_id=thread.thread_id, p_index=1, reply_message="Hi there", reply_as_reply=False)
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI()
    service = AutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=FakeNotifier(),
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            message_id="msg-1",
            content="hello there",
            sent_at=datetime.now(timezone.utc),
            raw_tags={"badges": ""},
        )
    )

    assert service.sent_replies == 1
    assert twitch_api.sent_messages[0]["message"] == "Hi there"


@pytest.mark.asyncio
async def test_channel_event_auto_reply_service_sends_message_when_channel_goes_live() -> None:
    bus = EventBus()
    thread_repository = InMemoryThreadRepository()
    thread = thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    channel_repository.add_channel(thread.thread_id, "42")
    channel_event_reply_repository = InMemoryChannelEventReplyRepository()
    channel_event_reply_repository.upsert_reply(
        thread_id=thread.thread_id,
        twitch_channel_id="42",
        event_state="online",
        reply_message="YIPPIE {CHANNEL} is {STATE}",
    )
    account_repository = InMemoryAccountRepository()
    account = account_repository.create_account(
        discord_user_id=200,
        twitch_user_id="77",
        twitch_login="dancedown",
        client_id="client-123",
        access_token="oauth:test-token",
        refresh_token=None,
        expires_at=None,
        scope=("user:write:chat",),
        token_type="bearer",
    )
    thread_repository.set_account_id(discord_channel_id=100, account_id=account.account_id)
    twitch_api = FakeTwitchAPI(
        users_by_id={
            "42": TwitchUser(user_id="42", login="example", display_name="ExampleChannel"),
        }
    )
    ChannelEventAutoReplyService(
        event_bus=bus,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        channel_event_reply_repository=channel_event_reply_repository,
        account_repository=account_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await bus.publish(
        EventType.TWITCH_CHANNEL_LIVE_STATE_CHANGED,
        TwitchChannelLiveStateChangedEvent(
            twitch_channel_id="42",
            twitch_channel_login="example",
            is_live=True,
        ),
    )

    assert len(twitch_api.sent_messages) == 1
    assert twitch_api.sent_messages[0]["broadcaster_id"] == "42"
    assert twitch_api.sent_messages[0]["message"] == "YIPPIE ExampleChannel is online"
