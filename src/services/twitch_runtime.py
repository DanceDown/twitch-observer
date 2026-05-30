"""Shared Twitch runtime helpers used across services and gateways."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.database.connection import (
    PatternRecord,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
)
from src.services.twitch_gateways import TwitchAuthGateway, TwitchUserLookup

logger = logging.getLogger(__name__)

TWITCH_ADAPTER_KEY = "twitch"
CHANNEL_SUBJECT_TYPE = "channel"
STREAM_ONLINE_EVENT_KEY = "stream.online"
STREAM_OFFLINE_EVENT_KEY = "stream.offline"
STREAM_EVENT_KEY_TO_STATE = {
    STREAM_ONLINE_EVENT_KEY: "online",
    STREAM_OFFLINE_EVENT_KEY: "offline",
}
DISCORD_NOTIFY_ACTION = "discord_notify"
TWITCH_SEND_MESSAGE_ACTION = "twitch_send_message"


async def ensure_fresh_linked_account(
    *,
    account: TwitchAccountRecord,
    account_repository: TwitchAccountRepository,
    twitch_auth: TwitchAuthGateway,
    token_refresh_skew_seconds: int,
    thread_repository: ThreadRepository | None = None,
    thread: ThreadRecord | None = None,
) -> TwitchAccountRecord | None:
    """Return a usable linked Twitch account, refreshing it when needed."""
    if account.expires_at is None:
        return account
    try:
        expires_at = datetime.fromisoformat(account.expires_at)
    except ValueError:
        return account
    if expires_at > datetime.now(UTC) + timedelta(seconds=token_refresh_skew_seconds):
        return account
    return (
        await refresh_linked_account(
            account=account,
            account_repository=account_repository,
            twitch_auth=twitch_auth,
            thread_repository=thread_repository,
            thread=thread,
        )
        or account
    )


async def refresh_linked_account(
    *,
    account: TwitchAccountRecord,
    account_repository: TwitchAccountRepository,
    twitch_auth: TwitchAuthGateway,
    thread_repository: ThreadRepository | None = None,
    thread: ThreadRecord | None = None,
) -> TwitchAccountRecord | None:
    """Refresh a linked Twitch account in storage and return the updated record."""
    if not account.refresh_token:
        return None
    try:
        refreshed = await twitch_auth.refresh_user_access_token(account.refresh_token)
        validated = await twitch_auth.validate_user_access_token(refreshed.access_token)
    except TwitchAPIError as error:
        logger.warning("Failed to refresh Twitch account for account_id=%s: %s", account.account_id, error)
        return None

    expires_at = (datetime.now(UTC) + timedelta(seconds=refreshed.expires_in)).isoformat()
    stored = account_repository.update_account(
        account_id=account.account_id,
        twitch_user_id=validated.user_id,
        twitch_login=validated.login,
        client_id=validated.client_id,
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token,
        expires_at=expires_at,
        scope=refreshed.scope,
        token_type=refreshed.token_type,
    )
    if stored is None and thread is not None and thread_repository is not None and thread.account_id is not None:
        account_repository.remove_by_account_id(thread.account_id)
        thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
    return stored


async def safe_get_twitch_user_by_login(twitch_lookup: TwitchUserLookup, login: str) -> TwitchUser | None:
    """Look up a Twitch user by login without letting lookup failures break the hot path."""
    normalized_login = login.strip().lower()
    if not normalized_login:
        return None
    try:
        cached = twitch_lookup.get_cached_user_by_login(normalized_login)
        if cached is not None and cached.profile_image_url:
            return cached
        return await twitch_lookup.get_user_by_login(normalized_login)
    except TwitchAPIError:
        return None


async def safe_get_twitch_user_by_id(twitch_lookup: TwitchUserLookup, user_id: str | None) -> TwitchUser | None:
    """Look up a Twitch user by ID without letting lookup failures break the hot path."""
    normalized_user_id = "" if user_id is None else user_id.strip()
    if not normalized_user_id:
        return None
    try:
        cached = twitch_lookup.get_cached_user_by_id(normalized_user_id)
        if cached is not None:
            return cached
        return await twitch_lookup.get_user_by_id(normalized_user_id)
    except TwitchAPIError:
        return None


def expand_pattern_for_tracked_users(
    pattern: PatternRecord,
    *,
    thread_id: int,
    tracked_user_repository: TrackedUserRepository | None,
) -> PatternRecord:
    """Resolve all tracked-user selectors to a concrete user-id list."""
    if pattern.user_scope_mode not in {"all_tracked", "all_tracked_except_selected"}:
        return pattern

    if tracked_user_repository is None:
        tracked_user_ids: tuple[str, ...] = ()
    else:
        tracked_user_ids = tuple(user.twitch_user_id for user in tracked_user_repository.list_users_for_thread(thread_id))
    if pattern.user_scope_mode == "all_tracked_except_selected":
        excluded_user_ids = set(pattern.user_scope_ids)
        tracked_user_ids = tuple(user_id for user_id in tracked_user_ids if user_id not in excluded_user_ids)

    return PatternRecord(
        thread_id=pattern.thread_id,
        pattern_id=pattern.pattern_id,
        regex=pattern.regex,
        channel_scope_mode=pattern.channel_scope_mode,
        channel_scope_ids=pattern.channel_scope_ids,
        user_scope_mode="only_selected",
        user_scope_ids=tracked_user_ids,
        sub_state=pattern.sub_state,
        offline_state=pattern.offline_state,
        is_regex=pattern.is_regex,
        case_sensitive=pattern.case_sensitive,
        color=pattern.color,
        disabled=pattern.disabled,
        notify=pattern.notify,
        priority=pattern.priority,
        reply_message=pattern.reply_message,
        reply_as_reply=pattern.reply_as_reply,
    )


def offline_state_allows(pattern: PatternRecord, live_status: bool | None) -> bool:
    """Return whether one pattern is allowed under the persisted live/offline state."""
    if pattern.offline_state == "both" or live_status is None:
        return True
    if pattern.offline_state == "online":
        return live_status
    if pattern.offline_state == "offline":
        return not live_status
    return False
