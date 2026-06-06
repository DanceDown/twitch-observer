"""Twitch scope resolution for pattern command requests."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    ThreadRecord,
    TrackedUserRepository,
)
from src.events.event_types import ChannelScopeMode, UserScopeMode
from src.localization import Localizer
from src.services.twitch_gateways import TwitchDirectoryGateway


@dataclass(slots=True)
class PatternFilterResolver:
    """Resolve and validate Twitch channel/user scopes for pattern commands."""

    channel_repository: ChannelRepository
    twitch_api: TwitchDirectoryGateway
    localizer: Localizer
    tracked_user_repository: TrackedUserRepository | None = None

    async def resolve_filters(
        self,
        *,
        channel_scope_mode: ChannelScopeMode,
        twitch_channel_logins: tuple[str, ...],
        user_scope_mode: UserScopeMode,
        twitch_user_logins: tuple[str, ...],
        thread: ThreadRecord,
    ):
        """Resolve optional Twitch filters and validate the configured channel scope."""
        if channel_scope_mode not in {
            ChannelScopeMode.ALL_TRACKED,
            ChannelScopeMode.ONLY_SELECTED,
            ChannelScopeMode.ALL_EXCEPT_SELECTED,
        }:
            raise ValueError(self._text(thread, "results.pattern.unsupported_channel_scope"))

        if channel_scope_mode is ChannelScopeMode.ALL_TRACKED and twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.unexpected_selected_channels"))

        if channel_scope_mode in {ChannelScopeMode.ONLY_SELECTED, ChannelScopeMode.ALL_EXCEPT_SELECTED} and not twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.missing_selected_channels"))

        scoped_channels = []
        for channel_login in twitch_channel_logins:
            channel_user = await self._resolve_user_by_login(channel_login)
            existing_channel = await self.channel_repository.get_by_thread_and_twitch_channel(
                    thread.thread_id,
                    channel_user.user_id,
                )
            
            if existing_channel is None:
                raise ValueError(
                    self._text(
                        thread,
                        "results.pattern.channel_not_tracked",
                        sources={"view": {"channel": {"display_name": channel_user.display_name, "login": channel_user.login}}},
                    )
                )
            scoped_channels.append(channel_user)

        if user_scope_mode not in {
            UserScopeMode.ALL_USERS,
            UserScopeMode.ALL_TRACKED,
            UserScopeMode.ONLY_SELECTED,
            UserScopeMode.ALL_EXCEPT_SELECTED,
            UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED,
        }:
            raise ValueError(self._text(thread, "results.pattern.unsupported_user_scope"))

        if user_scope_mode in {UserScopeMode.ALL_USERS, UserScopeMode.ALL_TRACKED} and twitch_user_logins:
            selected_user_logins: tuple[str, ...] = ()
        else:
            selected_user_logins = twitch_user_logins

        if (
            user_scope_mode
            in {
                UserScopeMode.ONLY_SELECTED,
                UserScopeMode.ALL_EXCEPT_SELECTED,
                UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED,
            }
            and not selected_user_logins
        ):
            raise ValueError(self._text(thread, "results.pattern.missing_selected_users"))

        scoped_users = []
        for user_login in selected_user_logins:
            resolved_user = await self._resolve_user_by_login(user_login)
            existing_user = (
                None
                if self.tracked_user_repository is None
                else await self.tracked_user_repository.get_by_thread_and_twitch_user(
                        thread.thread_id,
                        resolved_user.user_id,
                    )
                
            )
            if self.tracked_user_repository is not None and existing_user is None:
                raise ValueError(
                    self._text(
                        thread,
                        "results.pattern.user_not_tracked",
                        sources={"view": {"user": {"display_name": resolved_user.display_name, "login": resolved_user.login}}},
                    )
                )
            scoped_users.append(resolved_user)
        return scoped_channels, scoped_users

    async def resolve_pattern_edit_filters(
        self,
        *,
        channel_scope_mode: ChannelScopeMode | None,
        twitch_channel_logins: tuple[str, ...] | None,
        user_scope_mode: UserScopeMode | None,
        twitch_user_logins: tuple[str, ...] | None,
        thread: ThreadRecord,
        pattern: PatternRecord,
    ):
        effective_channel_scope_mode = pattern.channel_scope_mode if channel_scope_mode is None else channel_scope_mode.value
        effective_user_scope_mode = pattern.user_scope_mode if user_scope_mode is None else user_scope_mode.value

        if twitch_channel_logins is None:
            if channel_scope_mode is None:
                resolved_channel_logins = await self.resolve_channel_logins_from_ids(pattern.channel_scope_ids)
            else:
                resolved_channel_logins = ()
        else:
            resolved_channel_logins = twitch_channel_logins

        if twitch_user_logins is None:
            if user_scope_mode is None:
                resolved_user_logins = await self.resolve_user_logins_from_ids(pattern.user_scope_ids)
            else:
                resolved_user_logins = ()
        else:
            resolved_user_logins = twitch_user_logins

        return await self.resolve_filters(
            channel_scope_mode=ChannelScopeMode(effective_channel_scope_mode),
            twitch_channel_logins=resolved_channel_logins,
            user_scope_mode=UserScopeMode(effective_user_scope_mode),
            twitch_user_logins=resolved_user_logins,
            thread=thread,
        )

    async def resolve_channel_logins_from_ids(
        self,
        twitch_channel_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        logins: list[str] = []
        for twitch_channel_id in twitch_channel_ids:
            user = await self._resolve_channel_by_id(twitch_channel_id)
            logins.append(user.login)
        return tuple(logins)

    async def resolve_user_logins_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        logins: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            logins.append(user.login)
        return tuple(logins)

    async def resolve_display_names_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        names: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            names.append(user.display_name)
        return tuple(names)

    async def resolve_profile_items_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[dict[str, str], ...]:
        links: list[dict[str, str]] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            links.append({"display_name": user.display_name, "login": user.login})
        return tuple(links)

    async def _resolve_user_by_login(self, login: str):
        normalized_login = login.strip().lower()
        if normalized_login:
            cached = self.twitch_api.get_cached_user_by_login(normalized_login)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_login(login)

    async def _resolve_user_by_id(self, user_id: str):
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)

    async def _resolve_channel_by_id(self, user_id: str):
        return await self.twitch_api.get_channel_by_id(user_id)

    def _text(
        self,
        thread: ThreadRecord,
        key: str,
        *,
        sources: dict[str, object] | None = None,
    ) -> str:
        return self.localizer.text(
            key,
            language=self.localizer.language_for_thread(thread),
            sources=sources,
        )
