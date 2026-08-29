"""Focused `/show` renderer for auto replies and external reply actions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
)
from src.localization import Localizer
from src.services.twitch_runtime import STREAM_EVENT_KEY_TO_STATE, TWITCH_SEND_MESSAGE_ACTION

from .support import ShowTwitchSubjectResolver, stream_state_key
from .text import render_details, render_line, render_row, render_rows, render_section


@dataclass(slots=True)
class ShowAutoRepliesRenderer:
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository | None
    adapter_event_action_repository: AdapterEventActionRepository | None
    resolver: ShowTwitchSubjectResolver
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        replies = (
            []
            if self.reply_repository is None
            else await self.reply_repository.list_replies_for_thread(thread.thread_id, include_disabled=True)
        )
        adapter_event_actions = (
            []
            if self.adapter_event_action_repository is None
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
            return render_section(self.localizer, "show.auto_replies", language=language, section_body=empty_text)

        patterns = await self.pattern_repository.list_patterns_for_thread(thread.thread_id)
        pattern_map = {pattern.pattern_id: pattern for pattern in patterns}
        pattern_display_indices = {pattern.pattern_id: display_index for display_index, pattern in enumerate(patterns, start=1)}
        await self.resolver.preload_channel_ids(
            tuple(event.subject_id for event, _action in adapter_event_actions)
            + tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids)
        )
        await self.resolver.preload_user_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.user_scope_ids))

        rows: list[str] = []
        for reply in replies:
            pattern = pattern_map.get(reply.pattern_id)
            if pattern is None:
                continue
            display_index = pattern_display_indices.get(pattern.pattern_id, pattern.pattern_id)
            rows.append(
                self._build_pattern_reply_row(
                    display_index=display_index, trigger_text=pattern.regex, reply_text=reply.reply_message, language=language
                )
            )
        for adapter_event, action in adapter_event_actions:
            rows.append(await self._build_event_reply_row(adapter_event, action, language=language))
        if not rows:
            return render_section(self.localizer, "show.auto_replies", language=language, section_body=empty_text)
        return render_section(
            self.localizer,
            "show.auto_replies",
            language=language,
            section_body=render_rows(self.localizer, "show.auto_replies", language=language, items=tuple(rows)),
        )

    def _build_pattern_reply_row(self, *, display_index: int, trigger_text: str, reply_text: str, language: str) -> str:
        detail_items = (
            self.localizer.text("show.reply.trigger", language=language, sources={"view": {"text": trigger_text}}),
            self.localizer.text("show.reply.reply", language=language, sources={"view": {"text": reply_text}}),
        )
        return render_row(
            self.localizer,
            "show.reply",
            language=language,
            view={
                "head": render_line(self.localizer, "show.reply", language=language, view={"id": display_index}),
                "details": render_details(self.localizer, "show.reply", language=language, items=detail_items),
            },
        )

    async def _build_event_reply_row(
        self,
        event: AdapterEventRecord,
        action: AdapterEventActionRecord,
        *,
        language: str,
    ) -> str:
        channel_user = await self.resolver.resolve_channel_by_id(event.subject_id)
        state_label = self.localizer.lookup(
            "discord.live_state_ui.states.stream",
            stream_state_key(STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key)),
            language=language,
        )
        detail_items = [
            self.localizer.text(
                "show.event_reply.channel",
                language=language,
                sources={"view": {"display_name": channel_user.display_name, "login": channel_user.login}},
            ),
            self.localizer.text(
                "show.event_reply.reply",
                language=language,
                sources={"view": {"text": action.message_template or ""}},
            ),
        ]
        if action.disabled:
            detail_items.append(self.localizer.text("show.event_reply.disabled", language=language))
        return render_row(
            self.localizer,
            "show.event_reply",
            language=language,
            view={
                "head": render_line(self.localizer, "show.event_reply", language=language, view={"state": state_label}),
                "details": render_details(self.localizer, "show.event_reply", language=language, items=tuple(detail_items)),
            },
        )
