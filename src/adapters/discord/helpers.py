from __future__ import annotations

"""Shared Discord adapter helpers for command handlers and modals."""

import discord

from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.utils.discord_embeds import build_result_embed


async def send_initial_result(interaction: discord.Interaction, result: DiscordCommandResult) -> None:
    """Send the standardized embed response for a completed interaction."""
    embed = build_result_embed(result)
    if interaction.response.is_done():
        try:
            await interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            await interaction.followup.send(embed=embed, ephemeral=result.ephemeral)
        return
    await interaction.response.send_message(embed=embed, ephemeral=result.ephemeral)


def command_unavailable_result() -> DiscordCommandResult:
    """Build the shared error result used outside channel or DM contexts."""
    return DiscordCommandResult(
        title="Command Unavailable",
        message="This command can only be used inside a Discord channel or DM.",
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )


def normalize_optional_text(value: str | None) -> str | None:
    """Collapse empty strings and surrounding whitespace into `None`."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def split_csv_values(value: str | None) -> tuple[str, ...]:
    """Split a comma-separated slash-command field into normalized values."""
    normalized = normalize_optional_text(value)
    if normalized is None:
        return ()
    unique_values: list[str] = []
    for part in normalized.split(","):
        cleaned = part.strip()
        if cleaned and cleaned not in unique_values:
            unique_values.append(cleaned)
    return tuple(unique_values)
