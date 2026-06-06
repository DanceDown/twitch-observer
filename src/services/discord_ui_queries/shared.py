"""Shared helpers for Discord UI query services."""

from __future__ import annotations

from src.database.connection import ThreadRecord, ThreadRepository
from src.gateways.twitch_api import TwitchUser
from src.services.twitch_gateways import TwitchDirectoryGateway


async def get_thread_for_channel(thread_repository: ThreadRepository, discord_channel_id: int) -> ThreadRecord | None:
    return await thread_repository.get_by_discord_channel_id(discord_channel_id)


async def _load_cached_user_by_id(twitch_api: TwitchDirectoryGateway, user_id: str) -> TwitchUser | None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        return None
    return await twitch_api.load_cached_user_by_id(normalized_user_id)


async def resolve_users_by_ids(
    twitch_api: TwitchDirectoryGateway,
    user_ids: tuple[str, ...],
    *,
    channel_lookup: bool,
) -> dict[str, TwitchUser]:
    resolved: dict[str, TwitchUser] = {}
    normalized_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
    missing_ids: list[str] = []
    for user_id in normalized_ids:
        cached = await _load_cached_user_by_id(twitch_api, user_id)
        if cached is not None:
            resolved[user_id] = cached
        else:
            missing_ids.append(user_id)
    if missing_ids:
        for user in await twitch_api.get_users_by_ids(tuple(missing_ids)):
            resolved[user.user_id.strip()] = user
        unresolved_ids = [user_id for user_id in missing_ids if user_id not in resolved]
        for user_id in unresolved_ids:
            resolved[user_id] = await twitch_api.get_channel_by_id(user_id) if channel_lookup else await twitch_api.get_user_by_id(user_id)
    return resolved
