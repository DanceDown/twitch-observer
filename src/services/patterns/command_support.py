"""Shared helpers for pattern command handling."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import ChannelRepository, PatternRepository, ThreadRecord, TrackedUserRepository
from src.events.event_types import ChannelScopeMode, OfflineScope, SubscriptionScope, UserScopeMode
from src.localization import Localizer
from src.services.patterns.display_index import PatternDisplayIndexResolver
from src.services.patterns.filters import PatternFilterResolver
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

    def __post_init__(self) -> None:
        self._display_index = PatternDisplayIndexResolver(self.pattern_repository)
        self._filters = PatternFilterResolver(
            channel_repository=self.channel_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            localizer=self.localizer,
        )

    def text(
        self,
        thread: ThreadRecord | None,
        key: str,
        *,
        sources: dict[str, object] | None = None,
    ) -> str:
        return self.localizer.text(
            key,
            language=self.localizer.language_for_thread(thread),
            sources=sources,
        )

    def pattern_mode(self, is_regex: bool, *, language: str, scope: str) -> str:
        suffix = "regex" if is_regex else "word"
        return self.localizer.lookup(f"{scope}.mode_value", suffix, language=language)

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
        parts = [
            self.localizer.text(
                f"{key_prefix}.text",
                language=language,
                sources={"view": {"text": pattern.regex}},
            ),
            self.localizer.text(
                f"{key_prefix}.mode",
                language=language,
                sources={"view": {"ping_mode": self.pattern_mode(pattern.is_regex, language=language, scope=key_prefix)}},
            ),
        ]
        channel_scope = self._scope_text(
            mode=pattern.channel_scope_mode,
            selected=channel_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="channel",
        )
        user_scope = self._scope_text(
            mode=pattern.user_scope_mode,
            selected=user_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="user",
        )
        if channel_scope:
            parts.append(channel_scope)
        if user_scope:
            parts.append(user_scope)
        if pattern.sub_state != "all":
            parts.append(
                self.localizer.text(
                    f"{key_prefix}.subscribers_only" if pattern.sub_state == "subs" else f"{key_prefix}.non_subscribers_only",
                    language=language,
                )
            )
        if pattern.offline_state != "both":
            parts.append(
                self.localizer.text(
                    f"{key_prefix}.only_while_live" if pattern.offline_state == "online" else f"{key_prefix}.only_while_offline",
                    language=language,
                )
            )
        parts.append(
            self.localizer.text(
                f"{key_prefix}.case_sensitive_yes" if pattern.case_sensitive else f"{key_prefix}.case_sensitive_no",
                language=language,
            )
        )
        if pattern.color:
            parts.append(
                self.localizer.text(
                    f"{key_prefix}.custom_color",
                    language=language,
                    sources={"view": {"color": pattern.color}},
                )
            )
        parts.append(
            self.localizer.text(
                f"{key_prefix}.priority",
                language=language,
                sources={"view": {"priority": pattern.priority}},
            )
        )
        return self.localizer.text(
            f"{key_prefix}.list",
            language=language,
            sources={"view": {"items": tuple(parts)}},
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
        changes: list[str] = []
        if before.regex != after.regex:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.text",
                    language=language,
                    sources={"view": {"before": before.regex, "after": after.regex}},
                )
            )
        if before.is_regex != after.is_regex:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.mode",
                    language=language,
                    sources={
                        "view": {
                            "before": self.pattern_mode(before.is_regex, language=language, scope=key_prefix),
                            "after": self.pattern_mode(after.is_regex, language=language, scope=key_prefix),
                        }
                    },
                )
            )

        old_channel_scope = self._scope_text(
            mode=before.channel_scope_mode,
            selected=old_channel_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="channel",
        )
        new_channel_scope = self._scope_text(
            mode=after.channel_scope_mode,
            selected=new_channel_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="channel",
        )
        if old_channel_scope != new_channel_scope:
            all_channels_scope = self.localizer.text(f"{key_prefix}.scope.channel_all", language=language)
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.where",
                    language=language,
                    sources={"view": {"before": old_channel_scope or all_channels_scope, "after": new_channel_scope or all_channels_scope}},
                )
            )

        old_user_scope = self._scope_text(
            mode=before.user_scope_mode,
            selected=old_user_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="user",
        )
        new_user_scope = self._scope_text(
            mode=after.user_scope_mode,
            selected=new_user_logins,
            language=language,
            key_prefix=f"{key_prefix}.scope",
            subject="user",
        )
        if old_user_scope != new_user_scope:
            everyone_scope = self.localizer.text(f"{key_prefix}.scope.user_everyone", language=language)
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.who",
                    language=language,
                    sources={"view": {"before": old_user_scope or everyone_scope, "after": new_user_scope or everyone_scope}},
                )
            )
        if before.sub_state != after.sub_state:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.subscribers",
                    language=language,
                    sources={
                        "view": {
                            "before": self.localizer.text(f"{key_prefix}.sub_state.{before.sub_state}", language=language),
                            "after": self.localizer.text(f"{key_prefix}.sub_state.{after.sub_state}", language=language),
                        }
                    },
                )
            )
        if before.offline_state != after.offline_state:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.stream_state",
                    language=language,
                    sources={
                        "view": {
                            "before": self.localizer.text(f"{key_prefix}.stream_state_value.{before.offline_state}", language=language),
                            "after": self.localizer.text(f"{key_prefix}.stream_state_value.{after.offline_state}", language=language),
                        }
                    },
                )
            )
        if before.case_sensitive != after.case_sensitive:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.case_sensitive",
                    language=language,
                    sources={
                        "view": {
                            "before": self.localizer.text(
                                f"{key_prefix}.case_sensitive_yes" if before.case_sensitive else f"{key_prefix}.case_sensitive_no",
                                language=language,
                            ),
                            "after": self.localizer.text(
                                f"{key_prefix}.case_sensitive_yes" if after.case_sensitive else f"{key_prefix}.case_sensitive_no",
                                language=language,
                            ),
                        }
                    },
                )
            )
        if before.color != after.color:
            inherited_color = self.localizer.text(f"{key_prefix}.color_inherited", language=language)
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.color",
                    language=language,
                    sources={"view": {"before": before.color or inherited_color, "after": after.color or inherited_color}},
                )
            )
        if before.priority != after.priority:
            changes.append(
                self.localizer.text(
                    f"{key_prefix}.priority",
                    language=language,
                    sources={"view": {"before": before.priority, "after": after.priority}},
                )
            )
        return self.localizer.text(
            f"{key_prefix}.list",
            language=language,
            sources={"view": {"items": tuple(changes)}},
        )

    @staticmethod
    def profile_item(display_name: str, login: str) -> dict[str, str]:
        return {"display_name": display_name, "login": login}

    def _scope_text(
        self,
        *,
        mode: str,
        selected: tuple[dict[str, str], ...],
        language: str,
        key_prefix: str,
        subject: str,
    ) -> str | None:
        if mode == "all_users":
            return None
        if mode == "all_tracked":
            return self.localizer.text(f"{key_prefix}.{subject}_all", language=language)
        if mode == "only_selected":
            return self.localizer.text(
                f"{key_prefix}.{subject}_only",
                language=language,
                sources={"view": {"items": selected}},
            )
        if mode == "all_except_selected":
            return self.localizer.text(
                f"{key_prefix}.{subject}_except",
                language=language,
                sources={"view": {"items": selected}},
            )
        if mode == "all_tracked_except_selected":
            return self.localizer.text(
                f"{key_prefix}.{subject}_tracked_except",
                language=language,
                sources={"view": {"items": selected}},
            )
        return None

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
