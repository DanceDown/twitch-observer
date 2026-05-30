"""Localized presentation helpers for pattern command results."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import PatternRecord
from src.localization import Localizer


@dataclass(slots=True)
class PatternCommandPresenter:
    """Render localized pattern command summaries and change lists."""

    localizer: Localizer

    def format_pattern_summary(
        self,
        *,
        action: str,
        pattern: PatternRecord,
        display_id: int,
        channel_logins: tuple[str, ...],
        user_logins: tuple[str, ...],
        language: str,
    ) -> str:
        parts = [
            self.localizer.text(
                "results.pattern.summary.action",
                language=language,
                ACTION=action,
                ID=display_id,
            ),
            self.localizer.text(
                "results.pattern.summary.text",
                language=language,
                TEXT=pattern.regex,
            ),
            self.localizer.text(
                "results.pattern.summary.mode",
                language=language,
                PING_MODE=self.pattern_mode(pattern.is_regex, language=language, scope="summary"),
            ),
        ]
        channel_scope = self.scope_text(
            mode=pattern.channel_scope_mode,
            selected=channel_logins,
            language=language,
            key_prefix="results.pattern.summary.scope",
            subject="channel",
        )
        user_scope = self.scope_text(
            mode=pattern.user_scope_mode,
            selected=user_logins,
            language=language,
            key_prefix="results.pattern.summary.scope",
            subject="user",
        )
        if channel_scope:
            parts.append(channel_scope)
        if user_scope:
            parts.append(user_scope)
        if pattern.sub_state != "all":
            parts.append(
                self.localizer.text(
                    (
                        "results.pattern.summary.subscribers_only"
                        if pattern.sub_state == "subs"
                        else "results.pattern.summary.non_subscribers_only"
                    ),
                    language=language,
                )
            )
        if pattern.offline_state != "both":
            parts.append(
                self.localizer.text(
                    (
                        "results.pattern.summary.only_while_live"
                        if pattern.offline_state == "online"
                        else "results.pattern.summary.only_while_offline"
                    ),
                    language=language,
                )
            )
        parts.append(
            self.localizer.text(
                "results.pattern.summary.case_sensitive_yes"
                if pattern.case_sensitive
                else "results.pattern.summary.case_sensitive_no",
                language=language,
            )
        )
        if pattern.color:
            parts.append(
                self.localizer.text(
                    "results.pattern.summary.custom_color",
                    language=language,
                    COLOR=pattern.color,
                )
            )
        parts.append(
            self.localizer.text(
                "results.pattern.summary.priority",
                language=language,
                PRIORITY=pattern.priority,
            )
        )
        return self.localizer.text(
            "results.pattern.summary.list",
            language=language,
            ITEMS=tuple(parts),
        )

    def format_pattern_changes(
        self,
        *,
        before: PatternRecord,
        after: PatternRecord,
        display_id: int,
        old_channel_logins: tuple[str, ...],
        new_channel_logins: tuple[str, ...],
        old_user_logins: tuple[str, ...],
        new_user_logins: tuple[str, ...],
        language: str,
    ) -> str:
        changes = [
            self.localizer.text(
                "results.pattern.changes.updated",
                language=language,
                ID=display_id,
            )
        ]
        if before.regex != after.regex:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.text",
                    language=language,
                    BEFORE=before.regex,
                    AFTER=after.regex,
                )
            )
        if before.is_regex != after.is_regex:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.mode",
                    language=language,
                    BEFORE=self.pattern_mode(before.is_regex, language=language, scope="changes"),
                    AFTER=self.pattern_mode(after.is_regex, language=language, scope="changes"),
                )
            )

        old_channel_scope = self.scope_text(
            mode=before.channel_scope_mode,
            selected=old_channel_logins,
            language=language,
            key_prefix="results.pattern.changes.scope",
            subject="channel",
        )
        new_channel_scope = self.scope_text(
            mode=after.channel_scope_mode,
            selected=new_channel_logins,
            language=language,
            key_prefix="results.pattern.changes.scope",
            subject="channel",
        )
        if old_channel_scope != new_channel_scope:
            all_channels_scope = self.localizer.text("results.pattern.changes.scope.channel_all", language=language)
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.where",
                    language=language,
                    BEFORE=old_channel_scope or all_channels_scope,
                    AFTER=new_channel_scope or all_channels_scope,
                )
            )

        old_user_scope = self.scope_text(
            mode=before.user_scope_mode,
            selected=old_user_logins,
            language=language,
            key_prefix="results.pattern.changes.scope",
            subject="user",
        )
        new_user_scope = self.scope_text(
            mode=after.user_scope_mode,
            selected=new_user_logins,
            language=language,
            key_prefix="results.pattern.changes.scope",
            subject="user",
        )
        if old_user_scope != new_user_scope:
            everyone_scope = self.localizer.text("results.pattern.changes.scope.user_everyone", language=language)
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.who",
                    language=language,
                    BEFORE=old_user_scope or everyone_scope,
                    AFTER=new_user_scope or everyone_scope,
                )
            )
        if before.sub_state != after.sub_state:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.subscribers",
                    language=language,
                    BEFORE=self.sub_state(before.sub_state, language=language),
                    AFTER=self.sub_state(after.sub_state, language=language),
                )
            )
        if before.offline_state != after.offline_state:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.stream_state",
                    language=language,
                    BEFORE=self.offline_state(before.offline_state, language=language),
                    AFTER=self.offline_state(after.offline_state, language=language),
                )
            )
        if before.case_sensitive != after.case_sensitive:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.case_sensitive",
                    language=language,
                    BEFORE=self.case_sensitive_value(before.case_sensitive, language=language),
                    AFTER=self.case_sensitive_value(after.case_sensitive, language=language),
                )
            )
        if before.color != after.color:
            inherited_color = self.localizer.text("results.pattern.changes.color_inherited", language=language)
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.color",
                    language=language,
                    BEFORE=before.color or inherited_color,
                    AFTER=after.color or inherited_color,
                )
            )
        if before.priority != after.priority:
            changes.append(
                self.localizer.text(
                    "results.pattern.changes.priority",
                    language=language,
                    BEFORE=before.priority,
                    AFTER=after.priority,
                )
            )
        return self.localizer.text(
            "results.pattern.changes.list",
            language=language,
            ITEMS=tuple(changes),
        )

    def scope_text(
        self,
        *,
        mode: str,
        selected: tuple[str, ...],
        language: str,
        key_prefix: str,
        subject: str,
    ) -> str | None:
        if mode == "all_users":
            return None
        if mode == "all_tracked":
            return self.localizer.text(f"{key_prefix}.{subject}_all", language=language)
        if mode == "only_selected":
            return self._scope_text_with_items(
                key=f"{key_prefix}.{subject}_only",
                items=selected,
                language=language,
            )
        if mode == "all_except_selected":
            return self._scope_text_with_items(
                key=f"{key_prefix}.{subject}_except",
                items=selected,
                language=language,
            )
        if mode == "all_tracked_except_selected":
            return self._scope_text_with_items(
                key=f"{key_prefix}.{subject}_tracked_except",
                items=selected,
                language=language,
            )
        return None

    def pattern_mode(self, is_regex: bool, *, language: str, scope: str) -> str:
        key = f"results.pattern.{scope}.mode_value.regex" if is_regex else f"results.pattern.{scope}.mode_value.word"
        return self.localizer.text(key, language=language)

    def case_sensitive_value(self, value: bool, *, language: str) -> str:
        key = "results.pattern.changes.case_sensitive_yes" if value else "results.pattern.changes.case_sensitive_no"
        return self.localizer.text(key, language=language)

    def sub_state(self, value: str, *, language: str) -> str:
        return self.localizer.text(f"results.pattern.changes.sub_state.{value}", language=language)

    def offline_state(self, value: str, *, language: str) -> str:
        return self.localizer.text(f"results.pattern.changes.stream_state_value.{value}", language=language)

    def _scope_text_with_items(
        self,
        *,
        key: str,
        items: tuple[str, ...],
        language: str,
    ) -> str:
        return self.localizer.text(key, language=language, ITEMS=items)
