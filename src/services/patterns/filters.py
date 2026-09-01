"""Twitch scope resolution for pattern command requests."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    ThreadRecord,
    TrackedUserRepository,
)
from src.events.pattern_scopes import ChannelScopeMode, UserScopeMode
from src.gateways.twitch_api import TwitchUser
from src.localization import Localizer
from src.services.twitch_gateways import TwitchDirectoryGateway

_SUPPORTED_CHANNEL_SCOPE_MODES = frozenset(
    {
        ChannelScopeMode.ALL_TRACKED,
        ChannelScopeMode.ONLY_SELECTED,
        ChannelScopeMode.ALL_EXCEPT_SELECTED,
    }
)
_SELECTED_CHANNEL_SCOPE_MODES = frozenset(
    {
        ChannelScopeMode.ONLY_SELECTED,
        ChannelScopeMode.ALL_EXCEPT_SELECTED,
    }
)
_SUPPORTED_USER_SCOPE_MODES = frozenset(
    {
        UserScopeMode.ALL_USERS,
        UserScopeMode.ALL_TRACKED,
        UserScopeMode.ONLY_SELECTED,
        UserScopeMode.ALL_EXCEPT_SELECTED,
        UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED,
    }
)
_IGNORES_SELECTED_USER_SCOPE_MODES = frozenset({UserScopeMode.ALL_USERS, UserScopeMode.ALL_TRACKED})
_SELECTED_USER_SCOPE_MODES = frozenset(
    {
        UserScopeMode.ONLY_SELECTED,
        UserScopeMode.ALL_EXCEPT_SELECTED,
        UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED,
    }
)


@dataclass(slots=True, frozen=True)
class PatternEditFilterRequest:
    """Inputs needed to resolve the effective scopes for one pattern edit."""

    channel_scope_mode: ChannelScopeMode | None
    twitch_channel_logins: tuple[str, ...] | None
    user_scope_mode: UserScopeMode | None
    twitch_user_logins: tuple[str, ...] | None
    thread: ThreadRecord
    pattern: PatternRecord


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
    ) -> tuple[list[TwitchUser], list[TwitchUser]]:
        """Resolve optional Twitch filters and validate the configured channel scope."""
        self._validate_channel_scope(
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            thread=thread,
        )
        scoped_channels = await self._resolve_scoped_channels(thread=thread, twitch_channel_logins=twitch_channel_logins)
        selected_user_logins = self._selected_user_logins(
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
        )
        self._validate_user_scope(
            user_scope_mode=user_scope_mode,
            selected_user_logins=selected_user_logins,
            thread=thread,
        )
        scoped_users = await self._resolve_scoped_users(thread=thread, selected_user_logins=selected_user_logins)
        return scoped_channels, scoped_users

    def _validate_channel_scope(
        self,
        *,
        channel_scope_mode: ChannelScopeMode,
        twitch_channel_logins: tuple[str, ...],
        thread: ThreadRecord,
    ) -> None:
        if channel_scope_mode not in _SUPPORTED_CHANNEL_SCOPE_MODES:
            raise ValueError(self._text(thread, "results.pattern.unsupported_channel_scope"))
        if channel_scope_mode is ChannelScopeMode.ALL_TRACKED and twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.unexpected_selected_channels"))
        if channel_scope_mode in _SELECTED_CHANNEL_SCOPE_MODES and not twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.missing_selected_channels"))

    async def _resolve_scoped_channels(
        self,
        *,
        thread: ThreadRecord,
        twitch_channel_logins: tuple[str, ...],
    ) -> list[TwitchUser]:
        scoped_channels: list[TwitchUser] = []
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
        return scoped_channels

    @staticmethod
    def _selected_user_logins(
        *,
        user_scope_mode: UserScopeMode,
        twitch_user_logins: tuple[str, ...],
    ) -> tuple[str, ...]:
        if user_scope_mode in _IGNORES_SELECTED_USER_SCOPE_MODES and twitch_user_logins:
            return ()
        return twitch_user_logins

    def _validate_user_scope(
        self,
        *,
        user_scope_mode: UserScopeMode,
        selected_user_logins: tuple[str, ...],
        thread: ThreadRecord,
    ) -> None:
        if user_scope_mode not in _SUPPORTED_USER_SCOPE_MODES:
            raise ValueError(self._text(thread, "results.pattern.unsupported_user_scope"))
        if user_scope_mode in _SELECTED_USER_SCOPE_MODES and not selected_user_logins:
            raise ValueError(self._text(thread, "results.pattern.missing_selected_users"))

    async def _resolve_scoped_users(
        self,
        *,
        thread: ThreadRecord,
        selected_user_logins: tuple[str, ...],
    ) -> list[TwitchUser]:
        scoped_users: list[TwitchUser] = []
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
        return scoped_users

    async def resolve_pattern_edit_filters(self, request: PatternEditFilterRequest) -> tuple[list[TwitchUser], list[TwitchUser]]:
        """Resolve the effective Twitch filters after applying edit overrides."""
        effective_channel_scope_mode = (
            request.pattern.channel_scope_mode if request.channel_scope_mode is None else request.channel_scope_mode.value
        )
        effective_user_scope_mode = request.pattern.user_scope_mode if request.user_scope_mode is None else request.user_scope_mode.value

        if request.twitch_channel_logins is None:
            if request.channel_scope_mode is None:
                resolved_channel_logins = await self.resolve_channel_logins_from_ids(request.pattern.channel_scope_ids)
            else:
                resolved_channel_logins = ()
        else:
            resolved_channel_logins = request.twitch_channel_logins

        if request.twitch_user_logins is None:
            if request.user_scope_mode is None:
                resolved_user_logins = await self.resolve_user_logins_from_ids(request.pattern.user_scope_ids)
            else:
                resolved_user_logins = ()
        else:
            resolved_user_logins = request.twitch_user_logins

        return await self.resolve_filters(
            channel_scope_mode=ChannelScopeMode(effective_channel_scope_mode),
            twitch_channel_logins=resolved_channel_logins,
            user_scope_mode=UserScopeMode(effective_user_scope_mode),
            twitch_user_logins=resolved_user_logins,
            thread=request.thread,
        )

    async def resolve_channel_logins_from_ids(
        self,
        twitch_channel_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve Twitch channel IDs to logins for prefilled edit forms."""
        logins: list[str] = []
        for twitch_channel_id in twitch_channel_ids:
            user = await self._resolve_channel_by_id(twitch_channel_id)
            logins.append(user.login)
        return tuple(logins)

    async def resolve_user_logins_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve Twitch user IDs to logins for prefilled edit forms."""
        logins: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            logins.append(user.login)
        return tuple(logins)

    async def resolve_display_names_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve Twitch user IDs to display names for summaries."""
        names: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            names.append(user.display_name)
        return tuple(names)

    async def resolve_profile_items_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[dict[str, str], ...]:
        """Resolve Twitch user IDs to profile summary dictionaries."""
        links: list[dict[str, str]] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            links.append({"display_name": user.display_name, "login": user.login})
        return tuple(links)

    async def _resolve_user_by_login(self, login: str) -> TwitchUser:
        normalized_login = login.strip().lower()
        if normalized_login:
            cached = self.twitch_api.get_cached_user_by_login(normalized_login)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_login(login)

    async def _resolve_user_by_id(self, user_id: str) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)

    async def _resolve_channel_by_id(self, user_id: str) -> TwitchUser:
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
