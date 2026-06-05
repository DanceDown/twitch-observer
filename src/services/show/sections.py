"""Focused section renderers for `/show` overviews."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    TrackedUserRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.localization import Localizer
from src.services.channel_event_display_index import ChannelEventDisplayIndexResolver
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    DISCORD_NOTIFY_ACTION,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.permissions import explicit_permission_labels

from .support import ShowFormattingService, ShowTwitchSubjectResolver


@dataclass(slots=True)
class ShowChannelsRenderer:
    channel_repository: ChannelRepository
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        channels = await self.channel_repository.list_channels_for_thread(thread.thread_id)
        if not channels:
            return self.formatter.render_section(
                "show.channel.section",
                self.localizer.text("show.channel.empty", language=language),
                language=language,
            )

        await self.resolver.preload_channel_ids(tuple(channel.twitch_channel_id for channel in channels))
        rows: list[str] = []
        for channel in channels:
            twitch_user = await self.resolver.resolve_channel_by_id(channel.twitch_channel_id)
            details: list[str] = []
            if channel.color:
                details.append(
                    self.localizer.text(
                        "show.channel.custom_color",
                        language=language,
                        COLOR=channel.color,
                    )
                )
            rows.append(
                self.localizer.text(
                    "show.channel.row",
                    language=language,
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                    DETAILS=("" if not details else self.localizer.text("show.channel.details", language=language, ITEMS=tuple(details))),
                )
            )
        return self.formatter.render_section(
            "show.channel.section",
            self.localizer.text("show.channel.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )


@dataclass(slots=True)
class ShowChannelEventsRenderer:
    channel_repository: ChannelRepository
    adapter_event_action_repository: AdapterEventActionRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        if self.adapter_event_action_repository is None:
            return self.formatter.render_section(
                "show.channel_event.section",
                self.localizer.text("show.channel_event.empty", language=language),
                language=language,
            )

        channel_by_id = {
            channel.twitch_channel_id: channel
            for channel in await self.channel_repository.list_channels_for_thread(thread.thread_id)
        }
        rows: list[str] = []
        display_index_map = await ChannelEventDisplayIndexResolver(self.adapter_event_action_repository).build_index_map(thread.thread_id)
        actions = await self._channel_notification_actions(thread.thread_id)
        await self.resolver.preload_channel_ids(tuple(event.subject_id for event, _action in actions))
        for event, action in actions:
            display_index = display_index_map.get(event.event_id)
            if display_index is None:
                continue
            channel_user = await self.resolver.resolve_channel_by_id(event.subject_id)
            details = [
                self.localizer.text(
                    "show.channel_event.channel",
                    language=language,
                    DISPLAY_NAME=channel_user.display_name,
                    LOGIN=channel_user.login,
                ),
                self.localizer.text(
                    "show.channel_event.trigger",
                    language=language,
                    STATE=self.formatter.stream_state_label(
                        STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key),
                        language=language,
                    ),
                ),
            ]
            tracked_channel = channel_by_id.get(event.subject_id)
            if tracked_channel is not None and tracked_channel.is_live is not None:
                details.append(
                    self.localizer.text(
                        "show.channel_event.live_state",
                        language=language,
                        STATE=self.formatter.stream_state_label("online" if tracked_channel.is_live else "offline", language=language),
                    )
                )
            if action.color:
                details.append(
                    self.localizer.text(
                        "show.channel_event.custom_color",
                        language=language,
                        COLOR=action.color,
                    )
                )
            if action.disabled:
                details.append(self.localizer.text("show.channel_event.disabled", language=language))
            rows.append(
                self.formatter.render_row(
                    row_key="show.channel_event.row",
                    details_key="show.channel_event.details",
                    head=self.localizer.text("show.channel_event.line", language=language, ID=display_index),
                    details=details,
                    language=language,
                )
            )
        if not rows:
            return self.formatter.render_section(
                "show.channel_event.section",
                self.localizer.text("show.channel_event.empty", language=language),
                language=language,
            )
        return self.formatter.render_section(
            "show.channel_event.section",
            self.localizer.text("show.channel_event.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )

    async def _channel_notification_actions(self, thread_id: int) -> list[tuple[AdapterEventRecord, AdapterEventActionRecord]]:
        if self.adapter_event_action_repository is None:
            return []
        rows = [
            (event, action)
            for event, action in await self.adapter_event_action_repository.list_actions_for_thread(
                thread_id,
                include_disabled=True,
            )
            if action.action_type == DISCORD_NOTIFY_ACTION
            and event.adapter_key == TWITCH_ADAPTER_KEY
            and event.subject_type == CHANNEL_SUBJECT_TYPE
            and event.event_key in STREAM_EVENT_KEY_TO_STATE
        ]
        rows.sort(key=lambda item: item[0].event_id)
        return rows


@dataclass(slots=True)
class ShowPatternsRenderer:
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository | None
    adapter_event_repository: AdapterEventRepository | None
    adapter_event_action_repository: AdapterEventActionRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render_patterns(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        patterns = await self.pattern_repository.list_patterns_for_thread(thread.thread_id, is_regex=None)
        if not patterns:
            return self.formatter.render_section(
                "show.pattern.section",
                self.localizer.text("show.pattern.empty", language=language),
                language=language,
            )
        await self.resolver.preload_channel_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids))
        await self.resolver.preload_user_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.user_scope_ids))
        rows = [
            await self._format_pattern_row(pattern, display_index=display_index, language=language)
            for display_index, pattern in enumerate(patterns, start=1)
        ]
        return self.formatter.render_section(
            "show.pattern.section",
            self.localizer.text("show.pattern.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )

    async def render_auto_replies(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        replies = [] if self.reply_repository is None else await self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True)
        adapter_event_actions = (
            []
            if self.adapter_event_action_repository is None or self.adapter_event_repository is None
            else [
                (event_record, action_record)
                for event_record, action_record in await self.adapter_event_action_repository.list_actions_for_thread(
                    thread.thread_id,
                    include_disabled=True,
                )
                if action_record.action_type == TWITCH_SEND_MESSAGE_ACTION
            ]
        )
        empty_text = self.localizer.text("show.auto_replies.empty", language=language)
        if not replies and not adapter_event_actions:
            return self.formatter.render_section("show.auto_replies.section", empty_text, language=language)
        rows: list[str] = []
        patterns = await self.pattern_repository.list_patterns_for_thread(thread.thread_id)
        pattern_map = {pattern.pattern_id: pattern for pattern in patterns}
        pattern_display_indices = {pattern.pattern_id: display_index for display_index, pattern in enumerate(patterns, start=1)}
        await self.resolver.preload_channel_ids(
            tuple(event.subject_id for event, _action in adapter_event_actions)
            + tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids)
        )
        await self.resolver.preload_user_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.user_scope_ids))
        for reply in replies:
            pattern = pattern_map.get(reply.pattern_id)
            if pattern is None:
                continue
            display_index = pattern_display_indices.get(pattern.pattern_id, pattern.pattern_id)
            rows.append(
                self.formatter.render_row(
                    row_key="show.reply.row",
                    details_key="show.reply.details",
                    head=self.localizer.text("show.reply.line", language=language, ID=display_index),
                    details=[
                        self.localizer.text("show.reply.trigger", language=language, TEXT=pattern.regex),
                        self.localizer.text("show.reply.reply", language=language, TEXT=reply.reply_message),
                    ],
                    language=language,
                )
            )
        for adapter_event, action in adapter_event_actions:
            rows.append(await self._format_adapter_event_action_row(adapter_event, action, language=language))
        if not rows:
            return self.formatter.render_section("show.auto_replies.section", empty_text, language=language)
        return self.formatter.render_section(
            "show.auto_replies.section",
            self.localizer.text("show.auto_replies.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )

    async def _format_pattern_row(self, pattern: PatternRecord, *, display_index: int, language: str) -> str:
        details = [
            self.localizer.text("show.pattern.text", language=language, TEXT=pattern.regex),
            self.localizer.text(
                "show.pattern.mode",
                language=language,
                PING_MODE=self.localizer.text(
                    "show.pattern.mode_value.regex" if pattern.is_regex else "show.pattern.mode_value.word",
                    language=language,
                ),
            ),
        ]
        details.extend(await self._describe_pattern_details(pattern, language=language))
        return self.formatter.render_row(
            row_key="show.pattern.row",
            details_key="show.pattern.details",
            head=self.localizer.text("show.pattern.line", language=language, ID=display_index),
            details=details,
            language=language,
        )

    async def _format_adapter_event_action_row(
        self,
        event: AdapterEventRecord,
        action: AdapterEventActionRecord,
        *,
        language: str,
    ) -> str:
        channel_user = await self.resolver.resolve_channel_by_id(event.subject_id)
        state_label = self.formatter.stream_state_label(STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key), language=language)
        details = [
            self.localizer.text(
                "show.event_reply.channel",
                language=language,
                DISPLAY_NAME=channel_user.display_name,
                LOGIN=channel_user.login,
            ),
            self.localizer.text("show.event_reply.reply", language=language, TEXT=action.message_template or ""),
        ]
        if action.disabled:
            details.append(self.localizer.text("show.event_reply.disabled", language=language))
        return self.formatter.render_row(
            row_key="show.event_reply.row",
            details_key="show.event_reply.details",
            head=self.localizer.text("show.event_reply.line", language=language, STATE=state_label),
            details=details,
            language=language,
        )

    async def _describe_pattern_details(self, pattern: PatternRecord, *, language: str) -> list[str]:
        details: list[str] = []
        if pattern.channel_scope_mode != "all_tracked":
            channel_names = await self.resolver.resolve_twitch_links(pattern.channel_scope_ids)
            if pattern.channel_scope_mode == "only_selected":
                details.append(
                    self.localizer.text(
                        "show.pattern.where",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.channel_only", language=language, ITEMS=channel_names),
                    )
                )
            elif pattern.channel_scope_mode == "all_except_selected":
                details.append(
                    self.localizer.text(
                        "show.pattern.where",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.channel_except", language=language, ITEMS=channel_names),
                    )
                )
        if pattern.user_scope_mode != "all_users":
            user_names = await self.resolver.resolve_twitch_names(pattern.user_scope_ids)
            if pattern.user_scope_mode == "only_selected":
                details.append(
                    self.localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.user_only", language=language, ITEMS=user_names),
                    )
                )
            elif pattern.user_scope_mode == "all_except_selected":
                details.append(
                    self.localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.user_except", language=language, ITEMS=user_names),
                    )
                )
            elif pattern.user_scope_mode == "all_tracked":
                details.append(
                    self.localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.user_all", language=language),
                    )
                )
            elif pattern.user_scope_mode == "all_tracked_except_selected":
                details.append(
                    self.localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self.localizer.text("show.pattern.scope.user_tracked_except", language=language, ITEMS=user_names),
                    )
                )
        if pattern.sub_state != "all":
            details.append(
                self.localizer.text(
                    "show.pattern.subscribers_only" if pattern.sub_state == "subs" else "show.pattern.non_subscribers_only",
                    language=language,
                )
            )
        if pattern.offline_state != "both":
            details.append(
                self.localizer.text(
                    "show.pattern.only_while_live" if pattern.offline_state == "online" else "show.pattern.only_while_offline",
                    language=language,
                )
            )
        if pattern.case_sensitive:
            details.append(self.localizer.text("show.pattern.case_sensitive", language=language))
        if pattern.color:
            details.append(self.localizer.text("show.pattern.custom_color", language=language, COLOR=pattern.color))
        details.append(self.localizer.text("show.pattern.priority", language=language, PRIORITY=pattern.priority))
        if pattern.disabled:
            details.append(self.localizer.text("show.pattern.disabled", language=language))
        return details


@dataclass(slots=True)
class ShowUsersRenderer:
    tracked_user_repository: TrackedUserRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        empty_text = self.localizer.text("show.tracked_users.empty", language=language)
        if self.tracked_user_repository is None:
            return self.formatter.render_section("show.tracked_users.section", empty_text, language=language)
        tracked_users = await self.tracked_user_repository.list_users_for_thread(thread.thread_id)
        if not tracked_users:
            return self.formatter.render_section("show.tracked_users.section", empty_text, language=language)
        await self.resolver.preload_user_ids(tuple(tracked_user.twitch_user_id for tracked_user in tracked_users))
        rows = []
        for tracked_user in tracked_users:
            twitch_user = await self.resolver.resolve_user_by_id(tracked_user.twitch_user_id)
            rows.append({"DISPLAY_NAME": twitch_user.display_name, "LOGIN": twitch_user.login})
        return self.formatter.render_section(
            "show.tracked_users.section",
            self.localizer.text("show.tracked_users.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )


@dataclass(slots=True)
class ShowPermissionsRenderer:
    permission_repository: UserPermissionRepository | None
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        user_entries: list[str] = []
        permission_msg = self.localizer.value("show.show_permissions", language=language)
        if not isinstance(permission_msg, dict):
            raise ValueError("show.show_permissions must be an object.")
        body_template = permission_msg.get("body")
        user_list_item = permission_msg.get("user_list_item")
        if not isinstance(body_template, str) or not isinstance(user_list_item, str):
            raise ValueError("show.show_permissions must define body and user_list_item.")

        owner_permissions = self.localizer.text(
            "show.show_permissions.permission_list",
            language=language,
            PERMISSIONS=(self.localizer.text("show.show_permissions.permission_label.owner", language=language),),
        )
        user_entries.append(
            self.localizer.render(
                user_list_item,
                USERNAME=self.formatter.mention(thread.owner_id),
                PERMISSION_LIST=owner_permissions,
            )
        )
        rendered_user_list = self.formatter.render_permissions_user_list(user_entries, language=language)
        if self.permission_repository is None:
            return self.formatter.render_section(
                "show.show_permissions.section",
                self.localizer.render(body_template, USER_LIST=rendered_user_list),
                language=language,
            )

        for grant in await self.permission_repository.list_for_thread(thread_id=thread.thread_id):
            labels = explicit_permission_labels(grant.permissions)
            rendered = (
                [self.formatter.permission_label(label, language=language) for label in labels]
                if labels
                else [self.localizer.text("show.show_permissions.permission_label.none", language=language)]
            )
            permission_lines = self.localizer.text(
                "show.show_permissions.permission_list",
                language=language,
                PERMISSIONS=tuple(rendered),
            )
            user_entries.append(
                self.localizer.render(
                    user_list_item,
                    USERNAME=self.formatter.mention(grant.discord_user_id),
                    PERMISSION_LIST=permission_lines,
                )
            )
        rendered_user_list = self.formatter.render_permissions_user_list(user_entries, language=language)
        return self.formatter.render_section(
            "show.show_permissions.section",
            self.localizer.render(body_template, USER_LIST=rendered_user_list),
            language=language,
        )


@dataclass(slots=True)
class ShowAccountRenderer:
    account_repository: TwitchAccountRepository | None
    device_flow_repository: TwitchDeviceFlowRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> tuple[str, str | None]:
        language = self.localizer.language_for_thread(thread)
        rows: list[str] = []
        thumbnail_url = None
        account = (
            None
            if self.account_repository is None or thread.account_id is None
            else await self.account_repository.get_by_account_id(thread.account_id)
        )
        if account is not None:
            twitch_user = await self.resolver.resolve_user_by_id(account.twitch_user_id)
            thumbnail_url = twitch_user.profile_image_url
            rows.append(
                self.localizer.text(
                    "show.account.linked",
                    language=language,
                    USER=self.formatter.mention(account.discord_user_id),
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                )
            )
            rows.append(
                self.localizer.text(
                    "show.account.token_status",
                    language=language,
                    STATUS=self.localizer.text(
                        "show.account.token_available" if account.access_token else "show.account.token_missing",
                        language=language,
                    ),
                )
            )
        pending = (
            None
            if self.device_flow_repository is None
            else await self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)
        )
        if pending is not None:
            rows.append(
                self.localizer.text(
                    "show.account.pending",
                    language=language,
                    USER=self.formatter.mention(pending.discord_user_id),
                    STATUS=pending.status,
                    USER_CODE=pending.user_code,
                )
            )
        if not rows:
            rows.append(self.localizer.text("show.account.empty", language=language))
        return (
            self.formatter.render_section(
                "show.account.section",
                self.localizer.text("show.account.rows", language=language, ITEMS=tuple(rows)),
                language=language,
            ),
            thumbnail_url,
        )
