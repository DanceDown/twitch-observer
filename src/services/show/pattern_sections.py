"""Focused `/show` renderers for patterns and auto replies."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    PatternRecord,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
)
from src.localization import Localizer
from src.services.twitch_runtime import STREAM_EVENT_KEY_TO_STATE, TWITCH_SEND_MESSAGE_ACTION

from .support import ShowFormattingService, ShowTwitchSubjectResolver


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
        replies = (
            []
            if self.reply_repository is None
            else await self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True)
        )
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
        pattern_display_indices = {
            pattern.pattern_id: display_index for display_index, pattern in enumerate(patterns, start=1)
        }
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
        state_label = self.formatter.stream_state_label(
            STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key),
            language=language,
        )
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
