"""Shared helpers for pattern command handling."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import ChannelRepository, PatternRepository, ThreadRecord, TrackedUserRepository
from src.events.event_types import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from src.localization import Localizer
from src.services.patterns.display_index import PatternDisplayIndexResolver
from src.services.patterns.filters import PatternFilterResolver
from src.services.patterns.presentation import PatternCommandPresenter
from src.services.twitch_gateways import TwitchDirectoryGateway


@dataclass(slots=True)
class PatternCommandSupport:
    """Reusable localized helpers and resolvers for pattern commands."""

    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchDirectoryGateway
    localizer: Localizer
    tracked_user_repository: TrackedUserRepository | None = None
    _display_index: PatternDisplayIndexResolver = field(init=False, repr=False)
    _filters: PatternFilterResolver = field(init=False, repr=False)
    _presenter: PatternCommandPresenter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._display_index = PatternDisplayIndexResolver(self.pattern_repository)
        self._filters = PatternFilterResolver(
            channel_repository=self.channel_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            localizer=self.localizer,
        )
        self._presenter = PatternCommandPresenter(self.localizer)

    def text(
        self,
        thread: ThreadRecord | None,
        key: str,
        **placeholders: object,
    ) -> str:
        return self.localizer.text(
            key,
            language=self.localizer.language_for_thread(thread),
            **placeholders,
        )

    def pattern_mode(self, is_regex: bool, *, language: str, scope: str) -> str:
        suffix = "regex" if is_regex else "word"
        return self.localizer.text(f"{scope}.mode_value.{suffix}", language=language)

    async def display_index(self, thread_id: int, pattern_id: int) -> int | None:
        return await self._display_index.resolve(thread_id=thread_id, pattern_id=pattern_id)

    async def resolve_filters(
        self,
        *,
        channel_scope_mode: ChannelScopeMode,
        twitch_channel_logins: tuple[str, ...],
        user_scope_mode: UserScopeMode,
        twitch_user_logins: tuple[str, ...],
        thread: ThreadRecord,
    ):
        return await self._filters.resolve_filters(
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            thread=thread,
        )

    async def resolve_pattern_edit_filters(
        self,
        *,
        channel_scope_mode: ChannelScopeMode | None,
        twitch_channel_logins: tuple[str, ...] | None,
        user_scope_mode: UserScopeMode | None,
        twitch_user_logins: tuple[str, ...] | None,
        thread: ThreadRecord,
        pattern,
    ):
        return await self._filters.resolve_pattern_edit_filters(
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            thread=thread,
            pattern=pattern,
        )

    async def resolve_profile_items_from_ids(self, user_ids: tuple[str, ...]):
        return await self._filters.resolve_profile_items_from_ids(user_ids)

    def format_pattern_summary(
        self,
        *,
        pattern,
        channel_logins: tuple[dict[str, str], ...],
        user_logins: tuple[dict[str, str], ...],
        language: str,
        key_prefix: str,
    ) -> str:
        return self._presenter.format_pattern_summary(
            pattern=pattern,
            channel_logins=channel_logins,
            user_logins=user_logins,
            language=language,
            key_prefix=key_prefix,
        )

    def format_pattern_changes(
        self,
        *,
        before,
        after,
        old_channel_logins,
        new_channel_logins: tuple[dict[str, str], ...],
        old_user_logins,
        new_user_logins: tuple[dict[str, str], ...],
        language: str,
        key_prefix: str,
    ) -> str:
        return self._presenter.format_pattern_changes(
            before=before,
            after=after,
            old_channel_logins=old_channel_logins,
            new_channel_logins=new_channel_logins,
            old_user_logins=old_user_logins,
            new_user_logins=new_user_logins,
            language=language,
            key_prefix=key_prefix,
        )

    @staticmethod
    def profile_item(display_name: str, login: str) -> dict[str, str]:
        return {"DISPLAY_NAME": display_name, "LOGIN": login}

    @staticmethod
    def default_priority_for(
        *,
        channel_scope_mode: ChannelScopeMode,
        user_scope_mode: UserScopeMode,
        sub_state: SubscriptionScope,
        offline_state: OfflineScope,
    ) -> int:
        """Estimate a sensible default priority from rule specificity."""
        priority = 0
        if channel_scope_mode is ChannelScopeMode.ONLY_SELECTED:
            priority += 2
        elif channel_scope_mode is ChannelScopeMode.ALL_EXCEPT_SELECTED:
            priority += 1

        if user_scope_mode is UserScopeMode.ONLY_SELECTED:
            priority += 4
        elif user_scope_mode is UserScopeMode.ALL_EXCEPT_SELECTED:
            priority += 2
        elif user_scope_mode is UserScopeMode.ALL_TRACKED_EXCEPT_SELECTED:
            priority += 3

        if sub_state is not SubscriptionScope.ALL:
            priority += 1
        if offline_state is not OfflineScope.BOTH:
            priority += 1
        return min(priority, 9)
