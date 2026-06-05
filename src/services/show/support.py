"""Shared helpers for `/show` rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.gateways.twitch_api import TwitchUser
from src.localization import Localizer
from src.services.twitch_gateways import TwitchDirectoryGateway


@dataclass(slots=True)
class ShowFormattingService:
    """Shared localized formatting helpers for `/show` sections and rows."""

    localizer: Localizer

    def permission_label(self, label: str, *, language: str) -> str:
        return self.localizer.text(f"show.show_permissions.permission_label.{label}", language=language)

    def render_permissions_user_list(self, user_entries: list[str], *, language: str) -> str:
        return self.localizer.text("show.show_permissions.user_list", language=language, USER_LIST=tuple(user_entries))

    def render_section(self, wrapper_key: str, body: str, *, language: str) -> str:
        return self.localizer.text(wrapper_key, language=language, SECTION_BODY=body)

    def render_row(self, *, row_key: str, details_key: str, head: str, details: list[str], language: str) -> str:
        return self.localizer.text(
            row_key,
            language=language,
            HEAD=head,
            DETAILS=("" if not details else self.localizer.text(details_key, language=language, ITEMS=tuple(details))),
        )

    @staticmethod
    def mention(user_id: int) -> str:
        return f"<@{user_id}>"

    def stream_state_label(self, value: str, *, language: str) -> str:
        key = (
            "discord.live_state_ui.states.stream.online"
            if value in {"online", "live", "stream.online"}
            else "discord.live_state_ui.states.stream.offline"
        )
        return self.localizer.text(key, language=language)


@dataclass(slots=True)
class ShowTwitchSubjectResolver:
    """Resolve Twitch subjects once per render pass with small in-memory caches."""

    twitch_api: TwitchDirectoryGateway
    _channel_resolution_cache: dict[str, TwitchUser] = field(default_factory=dict, init=False, repr=False)
    _user_resolution_cache: dict[str, TwitchUser] = field(default_factory=dict, init=False, repr=False)

    def reset(self) -> None:
        self._channel_resolution_cache.clear()
        self._user_resolution_cache.clear()

    async def preload_channel_ids(self, twitch_ids: tuple[str, ...]) -> None:
        await self._resolve_ids_with_cache(
            twitch_ids,
            resolution_cache=self._channel_resolution_cache,
            channel_lookup=True,
        )

    async def preload_user_ids(self, twitch_ids: tuple[str, ...]) -> None:
        await self._resolve_ids_with_cache(
            twitch_ids,
            resolution_cache=self._user_resolution_cache,
            channel_lookup=False,
        )

    async def resolve_channel_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id not in self._channel_resolution_cache:
            await self.preload_channel_ids((user_id,))
        return self._channel_resolution_cache[normalized_user_id]

    async def resolve_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id not in self._user_resolution_cache:
            await self.preload_user_ids((user_id,))
        return self._user_resolution_cache[normalized_user_id]

    async def resolve_twitch_links(self, twitch_ids: tuple[str, ...]) -> tuple[dict[str, str], ...]:
        resolved: list[dict[str, str]] = []
        for twitch_id in twitch_ids:
            user = await self.resolve_channel_by_id(twitch_id)
            resolved.append({"DISPLAY_NAME": user.display_name, "LOGIN": user.login})
        return tuple(resolved)

    async def resolve_twitch_names(self, twitch_ids: tuple[str, ...]) -> tuple[dict[str, str], ...]:
        resolved: list[dict[str, str]] = []
        for twitch_id in twitch_ids:
            user = await self.resolve_user_by_id(twitch_id)
            resolved.append({"DISPLAY_NAME": user.display_name, "LOGIN": user.login})
        return tuple(resolved)

    async def _resolve_ids_with_cache(
        self,
        twitch_ids: tuple[str, ...],
        *,
        resolution_cache: dict[str, TwitchUser],
        channel_lookup: bool,
    ) -> None:
        normalized_ids = tuple(dict.fromkeys(twitch_id.strip() for twitch_id in twitch_ids if twitch_id.strip()))
        if not normalized_ids:
            return
        missing_ids: list[str] = []
        for twitch_id in normalized_ids:
            if twitch_id in resolution_cache:
                continue
            cached = await self.twitch_api.load_cached_user_by_id(twitch_id)
            if cached is not None:
                resolution_cache[twitch_id] = cached
            else:
                missing_ids.append(twitch_id)
        if missing_ids:
            for user in await self.twitch_api.get_users_by_ids(tuple(missing_ids)):
                resolution_cache[user.user_id.strip()] = user
            unresolved_ids = [twitch_id for twitch_id in missing_ids if twitch_id not in resolution_cache]
            for twitch_id in unresolved_ids:
                resolution_cache[twitch_id] = (
                    await self.twitch_api.get_channel_by_id(twitch_id)
                    if channel_lookup
                    else await self.twitch_api.get_user_by_id(twitch_id)
                )
