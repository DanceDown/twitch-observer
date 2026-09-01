"""Focused `/show` renderer for pattern configuration."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import PatternRecord, PatternRepository, ThreadRecord
from src.localization import Localizer

from .support import ShowTwitchSubjectResolver
from .text import render_details, render_empty_section, render_line, render_row, render_rows, render_section


@dataclass(slots=True)
class ShowPatternSectionRenderer:
    """Render ping and regex pattern configuration for `/show pings`."""

    pattern_repository: PatternRepository
    resolver: ShowTwitchSubjectResolver
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        """Return the localized pattern section for one thread."""
        language = self.localizer.language_for_thread(thread)
        patterns = await self.pattern_repository.list_patterns_for_thread(thread.thread_id, is_regex=None)
        if not patterns:
            return render_empty_section(self.localizer, "show.pattern", language=language)
        await self.resolver.preload_channel_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.channel_scope_ids))
        await self.resolver.preload_user_ids(tuple(twitch_id for pattern in patterns for twitch_id in pattern.user_scope_ids))
        rows = [
            await self._build_row(pattern, display_index=display_index, language=language)
            for display_index, pattern in enumerate(patterns, start=1)
        ]
        return render_section(
            self.localizer,
            "show.pattern",
            language=language,
            section_body=render_rows(self.localizer, "show.pattern", language=language, items=tuple(rows)),
        )

    async def _build_row(self, pattern: PatternRecord, *, display_index: int, language: str) -> str:
        details = [
            self.localizer.text("show.pattern.text", language=language, sources={"view": {"text": pattern.regex}}),
            self.localizer.text(
                "show.pattern.mode",
                language=language,
                sources={
                    "view": {
                        "ping_mode": self.localizer.lookup(
                            "show.pattern.mode_value",
                            "regex" if pattern.is_regex else "word",
                            language=language,
                        )
                    }
                },
            ),
        ]
        details.extend(await self._describe_details(pattern, language=language))
        return render_row(
            self.localizer,
            "show.pattern",
            language=language,
            view={
                "head": render_line(self.localizer, "show.pattern", language=language, view={"id": display_index}),
                "details": render_details(self.localizer, "show.pattern", language=language, items=tuple(details)),
            },
        )

    async def _describe_details(self, pattern: PatternRecord, *, language: str) -> list[str]:
        details: list[str] = []
        channel_scope_text = await self._channel_scope_text(pattern, language=language)
        if channel_scope_text:
            details.append(
                self.localizer.text(
                    "show.pattern.where",
                    language=language,
                    sources={"view": {"value": channel_scope_text}},
                )
            )
        user_scope_text = await self._user_scope_text(pattern, language=language)
        if user_scope_text:
            details.append(
                self.localizer.text(
                    "show.pattern.who",
                    language=language,
                    sources={"view": {"value": user_scope_text}},
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
            details.append(self.localizer.text("show.pattern.custom_color", language=language, sources={"view": {"color": pattern.color}}))
        details.append(self.localizer.text("show.pattern.priority", language=language, sources={"view": {"priority": pattern.priority}}))
        if pattern.disabled:
            details.append(self.localizer.text("show.pattern.disabled", language=language))
        return details

    async def _channel_scope_text(self, pattern: PatternRecord, *, language: str) -> str | None:
        if pattern.channel_scope_mode == "all_tracked":
            return None
        channel_names = await self.resolver.resolve_twitch_links(pattern.channel_scope_ids)
        if pattern.channel_scope_mode == "only_selected":
            return self.localizer.text(
                "show.pattern.scope.channel_only",
                language=language,
                sources={"view": {"items": channel_names}},
            )
        if pattern.channel_scope_mode == "all_except_selected":
            return self.localizer.text(
                "show.pattern.scope.channel_except",
                language=language,
                sources={"view": {"items": channel_names}},
            )
        return None

    async def _user_scope_text(self, pattern: PatternRecord, *, language: str) -> str | None:
        if pattern.user_scope_mode == "all_users":
            return None
        if pattern.user_scope_mode == "all_tracked":
            return self.localizer.text("show.pattern.scope.user_all", language=language)
        user_names = await self.resolver.resolve_twitch_names(pattern.user_scope_ids)
        key_by_mode = {
            "only_selected": "show.pattern.scope.user_only",
            "all_except_selected": "show.pattern.scope.user_except",
            "all_tracked_except_selected": "show.pattern.scope.user_tracked_except",
        }
        key = key_by_mode.get(pattern.user_scope_mode)
        if key is None:
            return None
        return self.localizer.text(
            key,
            language=language,
            sources={"view": {"items": user_names}},
        )
