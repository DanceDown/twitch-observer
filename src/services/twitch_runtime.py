"""Shared Twitch runtime helpers used across services and gateways."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from src.database.connection import (
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRecord,
    TwitchAccountRepository,
    TwitchAccountTokenData,
    TwitchAccountUpdate,
)
from src.gateways.twitch_api import TwitchAPIError, TwitchUser
from src.services.twitch_gateways import TwitchAuthGateway, TwitchUserChatColorLookup, TwitchUserLookup

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
TwitchUserFetcher = Callable[[str], Awaitable[TwitchUser]]

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


@dataclass(slots=True, frozen=True)
class LinkedTwitchAccountRefreshContext:
    """Dependencies needed to refresh and persist one linked Twitch account."""

    account_repository: TwitchAccountRepository
    twitch_auth: TwitchAuthGateway
    thread_repository: ThreadRepository | None = None
    thread: ThreadRecord | None = None


@dataclass(slots=True, frozen=True)
class _SafeTwitchUserRequest:
    cache_key: str
    cached: TwitchUser | None
    fetch: TwitchUserFetcher
    refresh: TwitchUserFetcher
    timeout_seconds: float | None
    require_chat_color: bool


async def ensure_fresh_linked_account(
    *,
    account: TwitchAccountRecord,
    context: LinkedTwitchAccountRefreshContext,
    token_refresh_skew_seconds: int,
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
            context=context,
        )
        or account
    )


async def refresh_linked_account(
    *,
    account: TwitchAccountRecord,
    context: LinkedTwitchAccountRefreshContext,
) -> TwitchAccountRecord | None:
    """Refresh a linked Twitch account in storage and return the updated record."""
    if not account.refresh_token:
        return None
    try:
        refreshed = await context.twitch_auth.refresh_user_access_token(account.refresh_token)
        validated = await context.twitch_auth.validate_user_access_token(refreshed.access_token)
    except TwitchAPIError as error:
        logger.warning("Failed to refresh Twitch account for account_id=%s: %s", account.account_id, error)
        return None

    expires_at = (datetime.now(UTC) + timedelta(seconds=refreshed.expires_in)).isoformat()
    stored = await context.account_repository.update_account(
        TwitchAccountUpdate(
            account_id=account.account_id,
            token=TwitchAccountTokenData(
                twitch_user_id=validated.user_id,
                twitch_login=validated.login,
                client_id=validated.client_id,
                access_token=refreshed.access_token,
                refresh_token=refreshed.refresh_token,
                expires_at=expires_at,
                scope=refreshed.scope,
                token_type=refreshed.token_type,
            ),
        )
    )

    if stored is None and context.thread is not None and context.thread_repository is not None and context.thread.account_id is not None:
        await context.account_repository.remove_by_account_id(context.thread.account_id)
        await context.thread_repository.set_account_id(
            discord_channel_id=context.thread.discord_channel_id,
            account_id=None,
        )
    return stored


async def safe_get_twitch_user_by_login(
    twitch_lookup: TwitchUserLookup,
    login: str,
    *,
    timeout_seconds: float | None = None,
    require_chat_color: bool = False,
) -> TwitchUser | None:
    """Look up a Twitch user by login without letting lookup failures break the hot path."""
    normalized_login = login.strip().lower()
    if not normalized_login:
        return None
    cached = twitch_lookup.get_cached_user_by_login(normalized_login)
    fetch = twitch_lookup.get_user_by_login
    refresh = twitch_lookup.refresh_user_by_login
    if require_chat_color and isinstance(twitch_lookup, TwitchUserChatColorLookup):
        fetch = twitch_lookup.get_user_by_login_with_chat_color
        refresh = twitch_lookup.refresh_user_by_login_with_chat_color
    return await _safe_get_twitch_user(
        _SafeTwitchUserRequest(
            cache_key=normalized_login,
            cached=cached,
            fetch=fetch,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            require_chat_color=require_chat_color,
        )
    )


async def safe_get_twitch_user_by_id(
    twitch_lookup: TwitchUserLookup,
    user_id: str | None,
    *,
    timeout_seconds: float | None = None,
    require_chat_color: bool = False,
) -> TwitchUser | None:
    """Look up a Twitch user by ID without letting lookup failures break the hot path."""
    normalized_user_id = "" if user_id is None else user_id.strip()
    if not normalized_user_id:
        return None
    cached = twitch_lookup.get_cached_user_by_id(normalized_user_id)
    fetch = twitch_lookup.get_user_by_id
    refresh = twitch_lookup.refresh_user_by_id
    if require_chat_color and isinstance(twitch_lookup, TwitchUserChatColorLookup):
        fetch = twitch_lookup.get_user_by_id_with_chat_color
        refresh = twitch_lookup.refresh_user_by_id_with_chat_color
    return await _safe_get_twitch_user(
        _SafeTwitchUserRequest(
            cache_key=normalized_user_id,
            cached=cached,
            fetch=fetch,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            require_chat_color=require_chat_color,
        )
    )


async def _safe_get_twitch_user(request: _SafeTwitchUserRequest) -> TwitchUser | None:
    try:
        if request.cached is not None and _has_complete_visual_metadata(
            request.cached,
            require_chat_color=request.require_chat_color,
        ):
            return request.cached
        if request.cached is not None:
            return await _with_optional_timeout(request.refresh(request.cache_key), request.timeout_seconds)
        user = await _with_optional_timeout(request.fetch(request.cache_key), request.timeout_seconds)
        if _has_complete_visual_metadata(user, require_chat_color=request.require_chat_color):
            return user
        return await _refresh_or_keep_user(
            cache_key=request.cache_key,
            fallback=user,
            refresh=request.refresh,
            timeout_seconds=request.timeout_seconds,
        )
    except (TwitchAPIError, TimeoutError):
        return request.cached


async def _refresh_or_keep_user(
    *,
    cache_key: str,
    fallback: TwitchUser,
    refresh: TwitchUserFetcher,
    timeout_seconds: float | None,
) -> TwitchUser:
    try:
        return await _with_optional_timeout(refresh(cache_key), timeout_seconds)
    except (TwitchAPIError, TimeoutError):
        return fallback


def _has_complete_visual_metadata(user: TwitchUser, *, require_chat_color: bool) -> bool:
    if not user.profile_image_url:
        return False
    return not require_chat_color or user.chat_color is not None


async def _with_optional_timeout(coro: Awaitable[_T], timeout_seconds: float | None) -> _T:
    if timeout_seconds is None or timeout_seconds <= 0:
        return await coro
    return await asyncio.wait_for(coro, timeout=timeout_seconds)
