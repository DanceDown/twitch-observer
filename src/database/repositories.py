"""Repository interfaces for PostgreSQL-backed persistence."""

from __future__ import annotations

from datetime import datetime

from src.events.twitch_events import TwitchChatMessageEvent

from .records import (
    AdapterEventActionRecord,
    AdapterEventRecord,
    ChannelRecord,
    ChatPatternCandidateRecord,
    ChatPatternSeedRecord,
    PatternCreate,
    PatternExactQuery,
    PatternRecord,
    PatternUpdate,
    RecentMessageRecord,
    ReplyRecord,
    SupportTicketCreate,
    SupportTicketRecord,
    ThreadRecord,
    TrackedChannelStateRecord,
    TrackedUserRecord,
    TwitchAccountCreate,
    TwitchAccountRecord,
    TwitchAccountUpdate,
    TwitchDeviceFlowRecord,
    TwitchDeviceFlowUpsert,
    TwitchUserCacheRecord,
    TwitchUserCacheUpsert,
    UserPermissionRecord,
)


class MessageRepository:
    """Persistence interface for normalized Twitch chat messages."""

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:  # pragma: no cover - interface
        """Persist one incoming Twitch chat message."""
        raise NotImplementedError

    async def save_bot_twitch_message(self, event: TwitchChatMessageEvent) -> None:  # pragma: no cover - interface
        """Persist one Twitch chat message sent by the bot."""
        raise NotImplementedError

    async def list_recent_messages(
        self,
        *,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:  # pragma: no cover - interface
        """Return recent Twitch messages across all tracked channels."""
        raise NotImplementedError

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:  # pragma: no cover - interface
        """Return recent Twitch messages for one broadcaster channel."""
        raise NotImplementedError

    async def mark_message_matched_in_thread(
        self,
        *,
        thread_id: int,
        event: TwitchChatMessageEvent,
    ) -> None:  # pragma: no cover - interface
        """Record that a Twitch message matched in one Discord thread."""
        raise NotImplementedError

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:  # pragma: no cover - interface
        """Return recent Twitch messages already linked to one thread."""
        raise NotImplementedError

    async def get_thread_message(
        self,
        *,
        thread_id: int,
        message_id: str,
    ) -> RecentMessageRecord | None:  # pragma: no cover - interface
        """Return one message previously matched in a thread."""
        raise NotImplementedError


class ThreadRepository:
    """Persistence interface for Discord thread/channel configuration roots."""

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:  # pragma: no cover
        """Return the configured thread for a Discord channel ID."""
        raise NotImplementedError

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:  # pragma: no cover
        """Return the configured thread for its internal ID."""
        raise NotImplementedError

    async def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:  # pragma: no cover
        """Create a Discord thread configuration root."""
        raise NotImplementedError

    async def delete_by_discord_channel_id(
        self,
        discord_channel_id: int,
    ) -> ThreadRecord | None:  # pragma: no cover
        """Delete a thread and its dependent configuration by Discord channel ID."""
        raise NotImplementedError

    async def set_enabled(
        self,
        *,
        discord_channel_id: int,
        enabled: bool,
    ) -> ThreadRecord | None:  # pragma: no cover
        """Enable or disable all bot behavior for one Discord channel."""
        raise NotImplementedError

    async def set_color(
        self,
        *,
        discord_channel_id: int,
        color: str | None,
    ) -> ThreadRecord | None:  # pragma: no cover
        """Set or clear the default embed color for one Discord channel."""
        raise NotImplementedError

    async def set_account_id(
        self,
        *,
        discord_channel_id: int,
        account_id: int | None,
    ) -> ThreadRecord | None:  # pragma: no cover
        """Attach or detach the linked Twitch account for one Discord channel."""
        raise NotImplementedError

    async def set_language(
        self,
        *,
        discord_channel_id: int,
        language: str,
    ) -> ThreadRecord | None:  # pragma: no cover
        """Set the localization language for one Discord channel."""
        raise NotImplementedError

    async def list_by_owner_id(self, owner_id: int) -> list[ThreadRecord]:  # pragma: no cover
        """Return all thread configurations owned by one Discord user."""
        raise NotImplementedError


class TwitchAccountRepository:
    """Persistence interface for linked Twitch accounts."""

    async def get_by_account_id(self, account_id: int) -> TwitchAccountRecord | None:  # pragma: no cover
        """Return one linked Twitch account by internal account ID."""
        raise NotImplementedError

    async def create_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:  # pragma: no cover
        """Create a linked Twitch account from validated token data."""
        raise NotImplementedError

    async def update_account(self, account: TwitchAccountUpdate) -> TwitchAccountRecord | None:  # pragma: no cover
        """Update token data for an existing linked Twitch account."""
        raise NotImplementedError

    async def remove_by_account_id(self, account_id: int) -> bool:  # pragma: no cover
        """Remove a linked Twitch account by internal account ID."""
        raise NotImplementedError

    async def get_by_discord_user_id(
        self,
        discord_user_id: int,
    ) -> TwitchAccountRecord | None:  # pragma: no cover
        """Return the linked Twitch account for one Discord user."""
        raise NotImplementedError

    async def upsert_account(self, account: TwitchAccountCreate) -> TwitchAccountRecord:  # pragma: no cover
        """Create or replace the linked Twitch account for a Discord user."""
        raise NotImplementedError

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover
        """Remove the linked Twitch account for one Discord user."""
        raise NotImplementedError

    async def list_accounts(self) -> list[TwitchAccountRecord]:  # pragma: no cover
        """Return all linked Twitch accounts."""
        raise NotImplementedError


class TwitchDeviceFlowRepository:
    """Persistence interface for pending Twitch Device Code logins."""

    async def get_by_discord_channel_id(
        self,
        discord_channel_id: int,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        """Return a pending device flow for one Discord channel."""
        raise NotImplementedError

    async def upsert_pending_flow(self, flow: TwitchDeviceFlowUpsert) -> TwitchDeviceFlowRecord:  # pragma: no cover
        """Create or replace a pending Twitch device flow."""
        raise NotImplementedError

    async def list_pending_flows(self) -> list[TwitchDeviceFlowRecord]:  # pragma: no cover
        """Return every pending Twitch device flow."""
        raise NotImplementedError

    async def mark_failed(
        self,
        *,
        discord_channel_id: int,
        last_error: str,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        """Mark the pending device flow for one channel as failed."""
        raise NotImplementedError

    async def touch_polled(self, *, discord_channel_id: int) -> None:  # pragma: no cover
        """Store that a pending device flow was just polled."""
        raise NotImplementedError

    async def update_interval(
        self,
        *,
        discord_channel_id: int,
        interval_seconds: int,
    ) -> None:  # pragma: no cover
        """Update Twitch's requested polling interval for a device flow."""
        raise NotImplementedError

    async def remove_by_discord_channel_id(self, discord_channel_id: int) -> bool:  # pragma: no cover
        """Remove a pending device flow by Discord channel ID."""
        raise NotImplementedError

    async def get_by_discord_user_id(
        self,
        discord_user_id: int,
    ) -> TwitchDeviceFlowRecord | None:  # pragma: no cover
        """Return a pending device flow for one Discord user."""
        raise NotImplementedError

    async def remove_by_discord_user_id(self, discord_user_id: int) -> bool:  # pragma: no cover
        """Remove a pending device flow by Discord user ID."""
        raise NotImplementedError


class TwitchUserCacheRepository:
    """Persistence interface for Twitch user metadata cached by ID and login."""

    async def get_by_user_id(self, twitch_user_id: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        """Return cached Twitch user metadata by Twitch user ID."""
        raise NotImplementedError

    async def get_by_login(self, twitch_login: str) -> TwitchUserCacheRecord | None:  # pragma: no cover
        """Return cached Twitch user metadata by Twitch login."""
        raise NotImplementedError

    async def upsert_from_api(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str,
        profile_image_url: str | None,
        chat_color: str | None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        """Persist Twitch user metadata fetched from the API."""
        raise NotImplementedError

    async def observe_from_chat(
        self,
        *,
        twitch_user_id: str,
        twitch_login: str,
        display_name: str | None,
        chat_color: str | None = None,
    ) -> TwitchUserCacheRecord:  # pragma: no cover
        """Persist cheap user metadata observed from IRC chat tags."""
        raise NotImplementedError

    async def list_all(self) -> list[TwitchUserCacheRecord]:  # pragma: no cover
        """Return all cached Twitch user metadata records."""
        raise NotImplementedError

    async def upsert_many_from_api(self, records: tuple[TwitchUserCacheUpsert, ...]) -> None:  # pragma: no cover
        """Persist a batch of Twitch user metadata records fetched from the API."""
        raise NotImplementedError


class ChannelRepository:
    """Persistence interface for per-thread channel subscriptions plus joined global live state."""

    async def get_by_thread_and_twitch_channel(
        self,
        thread_id: int,
        twitch_channel_id: str,
    ) -> ChannelRecord | None:  # pragma: no cover
        """Return one Twitch channel subscription inside a thread."""
        raise NotImplementedError

    async def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        """Add a Twitch channel subscription to a thread."""
        raise NotImplementedError

    async def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:  # pragma: no cover
        """Remove a Twitch channel subscription from a thread."""
        raise NotImplementedError

    async def set_color(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
        color: str | None,
    ) -> ChannelRecord | None:  # pragma: no cover
        """Set or clear a per-channel embed color override."""
        raise NotImplementedError

    async def set_live_state_for_twitch_channel(
        self,
        *,
        twitch_channel_id: str,
        is_live: bool,
        changed_at: str | None,
    ) -> int:  # pragma: no cover
        """Persist the shared live state for a Twitch channel."""
        raise NotImplementedError

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:  # pragma: no cover
        """Count thread subscriptions for one Twitch channel."""
        raise NotImplementedError

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:  # pragma: no cover
        """Return thread IDs that subscribe to one Twitch channel."""
        raise NotImplementedError

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:  # pragma: no cover
        """Return every Twitch channel subscription for one thread."""
        raise NotImplementedError

    async def list_all_twitch_channel_ids(self) -> list[str]:  # pragma: no cover
        """Return all distinct subscribed Twitch channel IDs."""
        raise NotImplementedError

    async def list_distinct_channel_states(self) -> list[TrackedChannelStateRecord]:  # pragma: no cover
        """Return one live-state row per subscribed Twitch channel."""
        raise NotImplementedError


class TrackedUserRepository:
    """Persistence interface for per-thread tracked Twitch users."""

    async def get_by_thread_and_twitch_user(
        self,
        thread_id: int,
        twitch_user_id: str,
    ) -> TrackedUserRecord | None:  # pragma: no cover
        """Return one tracked Twitch user inside a thread."""
        raise NotImplementedError

    async def add_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        """Add a tracked Twitch user to a thread."""
        raise NotImplementedError

    async def remove_user(self, thread_id: int, twitch_user_id: str) -> None:  # pragma: no cover
        """Remove a tracked Twitch user from a thread."""
        raise NotImplementedError

    async def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:  # pragma: no cover
        """Return every tracked Twitch user for one thread."""
        raise NotImplementedError

    async def count_pattern_scope_references(
        self,
        *,
        thread_id: int,
        twitch_user_id: str,
    ) -> int:  # pragma: no cover
        """Count pattern scopes that reference one tracked Twitch user."""
        raise NotImplementedError


class PatternRepository:
    """Persistence interface for per-thread ping/regex definitions."""

    async def find_exact_pattern(self, query: PatternExactQuery) -> PatternRecord | None:  # pragma: no cover
        """Return an existing pattern with the same normalized definition."""
        raise NotImplementedError

    async def add_pattern(self, pattern: PatternCreate) -> PatternRecord:  # pragma: no cover
        """Create a new ping or regex pattern."""
        raise NotImplementedError

    async def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:  # pragma: no cover
        """Remove one pattern from a thread."""
        raise NotImplementedError

    async def set_pattern_disabled(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        disabled: bool,
    ) -> PatternRecord | None:  # pragma: no cover
        """Enable or disable one pattern."""
        raise NotImplementedError

    async def set_pattern_priority(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        priority: int,
    ) -> PatternRecord | None:  # pragma: no cover
        """Update one pattern's matching priority."""
        raise NotImplementedError

    async def update_pattern(self, pattern: PatternUpdate) -> PatternRecord | None:  # pragma: no cover
        """Update a pattern definition and its scopes."""
        raise NotImplementedError

    async def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:  # pragma: no cover
        """Return enabled patterns for one thread."""
        raise NotImplementedError

    async def list_chat_match_seeds(
        self,
        *,
        broadcaster_id: str,
        author_id: str,
        sender_is_sub: bool,
    ) -> list[ChatPatternSeedRecord]:  # pragma: no cover
        """Return cheap candidate seeds for one incoming chat message."""
        raise NotImplementedError

    async def hydrate_chat_match_candidates(
        self,
        *,
        broadcaster_id: str,
        seeds: tuple[ChatPatternSeedRecord, ...],
    ) -> list[ChatPatternCandidateRecord]:  # pragma: no cover
        """Load full pattern records for selected chat-match seeds."""
        raise NotImplementedError

    async def get_pattern_by_id(
        self,
        *,
        thread_id: int,
        pattern_id: int,
    ) -> PatternRecord | None:  # pragma: no cover
        """Return one pattern by thread and display ID."""
        raise NotImplementedError

    async def list_patterns_for_thread(
        self,
        thread_id: int,
        *,
        is_regex: bool | None = None,
    ) -> list[PatternRecord]:  # pragma: no cover
        """Return patterns for one thread, optionally filtered by kind."""
        raise NotImplementedError

    async def count_channel_scope_references(
        self,
        *,
        thread_id: int,
        twitch_channel_id: str,
    ) -> int:  # pragma: no cover
        """Count pattern scopes that reference one tracked Twitch channel."""
        raise NotImplementedError


class ReplyRepository:
    """Persistence interface for auto-replies attached to patterns."""

    async def get_by_pattern(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:  # pragma: no cover
        """Return the auto-reply attached to one pattern."""
        raise NotImplementedError

    async def add_reply(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        reply_message: str,
        reply_as_reply: bool,
    ) -> ReplyRecord | None:  # pragma: no cover
        """Create or replace the auto-reply for one pattern."""
        raise NotImplementedError

    async def remove_reply(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:  # pragma: no cover
        """Remove the auto-reply from one pattern."""
        raise NotImplementedError

    async def set_reply_disabled(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        disabled: bool,
    ) -> ReplyRecord | None:  # pragma: no cover
        """Enable or disable the auto-reply for one pattern."""
        raise NotImplementedError

    async def list_replies_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[ReplyRecord]:  # pragma: no cover
        """Return auto-replies configured in one thread."""
        raise NotImplementedError

    async def disable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        """Disable every auto-reply in one thread and return the changed count."""
        raise NotImplementedError

    async def enable_replies_for_thread(self, thread_id: int) -> int:  # pragma: no cover
        """Enable every auto-reply in one thread and return the changed count."""
        raise NotImplementedError


class AdapterEventRepository:
    """Persistence interface for external adapter event triggers."""

    async def upsert_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord:  # pragma: no cover
        """Create or update an external adapter event trigger."""
        raise NotImplementedError

    async def get_event(
        self,
        *,
        thread_id: int,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
    ) -> AdapterEventRecord | None:  # pragma: no cover
        """Return one external adapter event trigger."""
        raise NotImplementedError

    async def list_events_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventRecord]:  # pragma: no cover
        """Return external adapter event triggers for one thread."""
        raise NotImplementedError

    async def list_matching_events(
        self,
        *,
        adapter_key: str,
        subject_type: str,
        subject_id: str,
        event_key: str,
        include_disabled: bool = False,
    ) -> list[AdapterEventRecord]:  # pragma: no cover
        """Return adapter events matching an incoming external event."""
        raise NotImplementedError


class AdapterEventActionRepository:
    """Persistence interface for follow-up actions on external adapter events."""

    async def upsert_action(
        self,
        *,
        event_id: int,
        action_type: str,
        message_template: str | None,
        reply_as_reply: bool,
    ) -> AdapterEventActionRecord:  # pragma: no cover
        """Create or update a follow-up action for an adapter event."""
        raise NotImplementedError

    async def get_action(
        self,
        *,
        event_id: int,
        action_type: str,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        """Return one follow-up action for an adapter event."""
        raise NotImplementedError

    async def remove_action(
        self,
        *,
        event_id: int,
        action_type: str,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        """Remove one follow-up action from an adapter event."""
        raise NotImplementedError

    async def set_action_disabled(
        self,
        *,
        event_id: int,
        action_type: str,
        disabled: bool,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        """Enable or disable one adapter-event follow-up action."""
        raise NotImplementedError

    async def set_action_color(
        self,
        *,
        event_id: int,
        action_type: str,
        color: str | None,
    ) -> AdapterEventActionRecord | None:  # pragma: no cover
        """Set or clear the embed color for an adapter-event action."""
        raise NotImplementedError

    async def list_actions_for_event(
        self,
        event_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[AdapterEventActionRecord]:  # pragma: no cover
        """Return follow-up actions for one adapter event."""
        raise NotImplementedError

    async def list_actions_for_thread(
        self,
        thread_id: int,
        *,
        include_disabled: bool = True,
    ) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:  # pragma: no cover
        """Return adapter-event actions joined with their event records."""
        raise NotImplementedError


class UserPermissionRepository:
    """Persistence interface for additional per-thread Discord permissions."""

    async def get_by_user_and_thread(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
    ) -> UserPermissionRecord | None:  # pragma: no cover
        """Return explicit permissions for one Discord user in one thread."""
        raise NotImplementedError

    async def upsert_permissions(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
        permissions: int,
    ) -> UserPermissionRecord:  # pragma: no cover
        """Create or update explicit permissions for one Discord user."""
        raise NotImplementedError

    async def remove_by_user_and_thread(
        self,
        *,
        discord_user_id: int,
        thread_id: int,
    ) -> bool:  # pragma: no cover
        """Remove explicit permissions for one Discord user in one thread."""
        raise NotImplementedError

    async def list_for_thread(self, *, thread_id: int) -> list[UserPermissionRecord]:  # pragma: no cover
        """Return every explicit permission grant in one thread."""
        raise NotImplementedError


class SupportTicketRepository:
    """Persistence interface for Discord support tickets."""

    async def create_ticket(self, ticket: SupportTicketCreate) -> SupportTicketRecord:  # pragma: no cover - interface
        """Create a Discord support ticket."""
        raise NotImplementedError

    async def set_support_message_id(
        self,
        *,
        ticket_id: int,
        support_message_id: int,
    ) -> SupportTicketRecord | None:  # pragma: no cover - interface
        """Attach the support-channel Discord message ID to a ticket."""
        raise NotImplementedError

    async def get_ticket(self, *, ticket_id: int) -> SupportTicketRecord | None:  # pragma: no cover - interface
        """Return one support ticket by ID."""
        raise NotImplementedError

    async def list_open_tickets_with_messages(self) -> list[SupportTicketRecord]:  # pragma: no cover - interface
        """Return open tickets that already have support-channel messages."""
        raise NotImplementedError

    async def answer_ticket(
        self,
        *,
        ticket_id: int,
        responder_discord_user_id: int,
        response_subject: str,
        response_body: str,
    ) -> SupportTicketRecord | None:  # pragma: no cover - interface
        """Mark an open support ticket as answered."""
        raise NotImplementedError

    async def close_ticket(
        self,
        *,
        ticket_id: int,
        closer_discord_user_id: int,
    ) -> SupportTicketRecord | None:  # pragma: no cover - interface
        """Mark an open support ticket as closed."""
        raise NotImplementedError
