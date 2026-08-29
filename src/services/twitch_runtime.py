"""Shared Twitch runtime helpers used across services and gateways."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
)
from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.services.twitch_gateways import TwitchAuthGateway, TwitchUserLookup

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

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
    stored = await account_repository.update_account(
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
        await account_repository.remove_by_account_id(thread.account_id)
        await thread_repository.set_account_id(discord_channel_id=thread.discord_channel_id, account_id=None)
    return stored


async def safe_get_twitch_user_by_login(
    twitch_lookup: TwitchUserLookup,
    login: str,
    *,
    timeout_seconds: float | None = None,
) -> TwitchUser | None:
    """Look up a Twitch user by login without letting lookup failures break the hot path."""
    normalized_login = login.strip().lower()
    if not normalized_login:
        return None
    cached = twitch_lookup.get_cached_user_by_login(normalized_login)
    try:
        if cached is not None and cached.profile_image_url:
            return cached
        if cached is not None:
            return await _with_optional_timeout(twitch_lookup.refresh_user_by_login(normalized_login), timeout_seconds)
        user = await _with_optional_timeout(twitch_lookup.get_user_by_login(normalized_login), timeout_seconds)
        if user.profile_image_url:
            return user
        try:
            return await _with_optional_timeout(twitch_lookup.refresh_user_by_login(normalized_login), timeout_seconds)
        except (TwitchAPIError, TimeoutError):
            return user
    except (TwitchAPIError, TimeoutError):
        return cached


async def safe_get_twitch_user_by_id(
    twitch_lookup: TwitchUserLookup,
    user_id: str | None,
    *,
    timeout_seconds: float | None = None,
) -> TwitchUser | None:
    """Look up a Twitch user by ID without letting lookup failures break the hot path."""
    normalized_user_id = "" if user_id is None else user_id.strip()
    if not normalized_user_id:
        return None
    cached = twitch_lookup.get_cached_user_by_id(normalized_user_id)
    try:
        if cached is not None and cached.profile_image_url:
            return cached
        if cached is not None:
            return await _with_optional_timeout(twitch_lookup.refresh_user_by_id(normalized_user_id), timeout_seconds)
        user = await _with_optional_timeout(twitch_lookup.get_user_by_id(normalized_user_id), timeout_seconds)
        if user.profile_image_url:
            return user
        try:
            return await _with_optional_timeout(twitch_lookup.refresh_user_by_id(normalized_user_id), timeout_seconds)
        except (TwitchAPIError, TimeoutError):
            return user
    except (TwitchAPIError, TimeoutError):
        return cached


async def _with_optional_timeout(coro: Awaitable[_T], timeout_seconds: float | None) -> _T:
    if timeout_seconds is None or timeout_seconds <= 0:
        return await coro
    return await asyncio.wait_for(coro, timeout=timeout_seconds)
