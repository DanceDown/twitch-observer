"""Localized display helpers for the ping UI."""

from __future__ import annotations

from src.localization import Localizer


def channel_scope_text(localizer: Localizer, language: str, mode: str, selected: list[str]) -> str:
    """Render one human-friendly summary for the channel scope."""
    if mode == "all_tracked":
        return localizer.text("discord.pattern_ui.summary.channel_scope_all", language=language)
    if mode == "only_selected":
        return (
            localizer.text("discord.pattern_ui.summary.channel_scope_only", language=language, ITEMS=selected)
            if selected
            else localizer.text("discord.pattern_ui.summary.channel_scope_only_invalid", language=language)
        )
    if mode == "all_except_selected":
        return (
            localizer.text("discord.pattern_ui.summary.channel_scope_except", language=language, ITEMS=selected)
            if selected
            else localizer.text("discord.pattern_ui.summary.channel_scope_except_invalid", language=language)
        )
    return mode


def user_scope_text(localizer: Localizer, language: str, mode: str, selected: list[str]) -> str:
    """Render one human-friendly summary for the user scope."""
    if mode == "all_users":
        return localizer.text("discord.pattern_ui.summary.user_scope_everyone", language=language)
    if mode == "all_tracked":
        return localizer.text("discord.pattern_ui.summary.user_scope_all_tracked", language=language)
    if mode == "all_tracked_except_selected":
        return (
            localizer.text("discord.pattern_ui.summary.user_scope_all_tracked_except", language=language, ITEMS=selected)
            if selected
            else localizer.text("discord.pattern_ui.summary.user_scope_all_tracked_except_invalid", language=language)
        )
    if mode == "only_selected":
        return (
            localizer.text("discord.pattern_ui.summary.user_scope_only", language=language, ITEMS=selected)
            if selected
            else localizer.text("discord.pattern_ui.summary.user_scope_only_invalid", language=language)
        )
    if mode == "all_except_selected":
        return (
            localizer.text("discord.pattern_ui.summary.user_scope_except", language=language, ITEMS=selected)
            if selected
            else localizer.text("discord.pattern_ui.summary.user_scope_except_invalid", language=language)
        )
    return mode


def sub_state_text(localizer: Localizer, language: str, value: str) -> str:
    """Render the subscriber scope in friendly language."""
    return {
        "all": localizer.text("discord.pattern_ui.summary.sub_state_all", language=language),
        "subs": localizer.text("discord.pattern_ui.summary.sub_state_subs", language=language),
        "non_subs": localizer.text("discord.pattern_ui.summary.sub_state_non_subs", language=language),
    }.get(value, value)


def offline_state_text(localizer: Localizer, language: str, value: str) -> str:
    """Render the stream-state filter in friendly language."""
    return {
        "both": localizer.text("discord.pattern_ui.summary.offline_state_both", language=language),
        "online": localizer.text("discord.pattern_ui.summary.offline_state_online", language=language),
        "offline": localizer.text("discord.pattern_ui.summary.offline_state_offline", language=language),
    }.get(value, value)
