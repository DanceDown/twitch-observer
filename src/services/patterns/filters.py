"""Twitch scope resolution for pattern command requests."""

from __future__ import annotations

from dataclasses import dataclass

from src.adapters.twitch_api import TwitchAPIClient
from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    ThreadRecord,
    TrackedUserRepository,
)
from src.events.event_types import DiscordPatternEditRequestedEvent, DiscordPatternRequestedEvent
from src.localization import Localizer
from src.utils.discord_embeds import format_twitch_code_link


@dataclass(slots=True)
class PatternFilterResolver:
    """Resolve and validate Twitch channel/user scopes for pattern commands."""

    channel_repository: ChannelRepository
    twitch_api: TwitchAPIClient
    localizer: Localizer
    tracked_user_repository: TrackedUserRepository | None = None

    async def resolve_filters(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ):
        """Resolve optional Twitch filters and validate the configured channel scope."""
        if event.channel_scope_mode not in {
            "all_tracked",
            "only_selected",
            "all_except_selected",
        }:
            raise ValueError(self._text(thread, "results.pattern.unsupported_channel_scope"))

        if event.channel_scope_mode == "all_tracked" and event.twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.unexpected_selected_channels"))

        if event.channel_scope_mode in {"only_selected", "all_except_selected"} and not event.twitch_channel_logins:
            raise ValueError(self._text(thread, "results.pattern.missing_selected_channels"))

        scoped_channels = []
        for channel_login in event.twitch_channel_logins:
            channel_user = await self._resolve_user_by_login(channel_login)
            existing_channel = self.channel_repository.get_by_thread_and_twitch_channel(
                thread.thread_id,
                channel_user.user_id,
            )
            if existing_channel is None:
                raise ValueError(
                    self._text(
                        thread,
                        "results.pattern.channel_not_tracked",
                        DISPLAY_NAME=channel_user.display_name,
                        LOGIN=channel_user.login,
                    )
                )
            scoped_channels.append(channel_user)

        if event.user_scope_mode not in {
            "all_users",
            "all_tracked",
            "only_selected",
            "all_except_selected",
            "all_tracked_except_selected",
        }:
            raise ValueError(self._text(thread, "results.pattern.unsupported_user_scope"))

        if event.user_scope_mode in {"all_users", "all_tracked"} and event.twitch_user_logins:
            event_user_logins: tuple[str, ...] = ()
        else:
            event_user_logins = event.twitch_user_logins

        if event.user_scope_mode in {"only_selected", "all_except_selected", "all_tracked_except_selected"} and not event_user_logins:
            raise ValueError(self._text(thread, "results.pattern.missing_selected_users"))

        scoped_users = []
        for user_login in event_user_logins:
            resolved_user = await self._resolve_user_by_login(user_login)
            existing_user = (
                None
                if self.tracked_user_repository is None
                else self.tracked_user_repository.get_by_thread_and_twitch_user(
                    thread.thread_id,
                    resolved_user.user_id,
                )
            )
            if self.tracked_user_repository is not None and existing_user is None:
                raise ValueError(
                    self._text(
                        thread,
                        "results.pattern.user_not_tracked",
                        DISPLAY_NAME=resolved_user.display_name,
                        LOGIN=resolved_user.login,
                    )
                )
            scoped_users.append(resolved_user)
        return scoped_channels, scoped_users

    async def resolve_pattern_edit_filters(
        self,
        event: DiscordPatternEditRequestedEvent,
        thread: ThreadRecord,
        pattern: PatternRecord,
    ):
        channel_scope_mode = pattern.channel_scope_mode if event.channel_scope_mode is None else event.channel_scope_mode
        user_scope_mode = pattern.user_scope_mode if event.user_scope_mode is None else event.user_scope_mode

        if event.twitch_channel_logins is None:
            if event.channel_scope_mode is None:
                twitch_channel_logins = await self.resolve_channel_logins_from_ids(
                    pattern.channel_scope_ids,
                )
            else:
                twitch_channel_logins = ()
        else:
            twitch_channel_logins = event.twitch_channel_logins

        if event.twitch_user_logins is None:
            if event.user_scope_mode is None:
                twitch_user_logins = await self.resolve_user_logins_from_ids(
                    pattern.user_scope_ids,
                )
            else:
                twitch_user_logins = ()
        else:
            twitch_user_logins = event.twitch_user_logins

        resolved_event = DiscordPatternRequestedEvent(
            discord_channel_id=event.discord_channel_id,
            requester_id=event.requester_id,
            action="add",
            pattern_text=event.pattern_text,
            pattern_id=event.pattern_id,
            is_regex=pattern.is_regex if event.is_regex is None else event.is_regex,
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            sub_state=pattern.sub_state if event.sub_state is None else event.sub_state,
            offline_state=(pattern.offline_state if event.offline_state is None else event.offline_state),
            case_sensitive=(pattern.case_sensitive if event.case_sensitive is None else event.case_sensitive),
            color=event.color,
            disabled=pattern.disabled,
            priority=event.priority,
            result_future=event.result_future,
        )
        return await self.resolve_filters(resolved_event, thread)

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

    async def resolve_profile_links_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
        *,
        language: str,
    ) -> tuple[str, ...]:
        links: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self._resolve_user_by_id(twitch_user_id)
            links.append(
                format_twitch_code_link(
                    localizer=self.localizer,
                    language=language,
                    display_name=user.display_name,
                    login=user.login,
                )
            )
        return tuple(links)

    async def _resolve_user_by_login(self, login: str):
        cached_lookup = getattr(self.twitch_api, "get_cached_user_by_login", None)
        normalized_login = login.strip().lower()
        if callable(cached_lookup) and normalized_login:
            cached = cached_lookup(normalized_login)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_login(login)

    async def _resolve_user_by_id(self, user_id: str):
        cached_lookup = getattr(self.twitch_api, "get_cached_user_by_id", None)
        normalized_user_id = user_id.strip()
        if callable(cached_lookup) and normalized_user_id:
            cached = cached_lookup(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)

    async def _resolve_channel_by_id(self, user_id: str):
        get_channel = getattr(self.twitch_api, "get_channel_by_id", None)
        if callable(get_channel):
            return await get_channel(user_id)
        return await self._resolve_user_by_id(user_id)

    def _text(
        self,
        thread: ThreadRecord,
        key: str,
        **placeholders: object,
    ) -> str:
        return self.localizer.text(
            key,
            language=self.localizer.language_for_thread(thread),
            **placeholders,
        )

