"""State helpers for reply command entrypoints."""

from __future__ import annotations

from ..ui_data import DiscordUIDataProvider


async def resolve_pattern_identifier(
    ui_data_provider: DiscordUIDataProvider,
    discord_channel_id: int,
    pattern_id: int,
) -> int:
    patterns = await ui_data_provider.list_patterns(discord_channel_id)
    for item in patterns:
        if item.pattern.pattern_id == pattern_id:
            return item.pattern.pattern_id
    for item in patterns:
        if item.display_index == pattern_id:
            return item.pattern.pattern_id
    return pattern_id
