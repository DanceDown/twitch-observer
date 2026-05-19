"""Twitch live-state queries split from user-directory lookup responsibilities."""

from __future__ import annotations

from dataclasses import dataclass

from src.gateways.twitch_api import TwitchAPIClient


@dataclass(slots=True)
class TwitchLiveQueryService:
    """Query Twitch for currently live broadcasters."""

    twitch_api: TwitchAPIClient

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        return await self.twitch_api.get_live_user_ids(user_ids)
