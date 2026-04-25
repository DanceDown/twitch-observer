from __future__ import annotations

"""Shared Discord adapter helpers for command handlers and modals."""

from contextlib import suppress

import discord

from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed


def _build_public_actor_embed(result: DiscordCommandResult, actor_mention: str) -> discord.Embed:
    """Render one public result embed that names the Discord user who triggered it."""
    embed = build_result_embed(result)
    embed.description = f"{actor_mention} {result.message}"
    return embed


async def send_initial_result(interaction: discord.Interaction, result: DiscordCommandResult) -> None:
    """Send the standardized embed response for a completed interaction."""
    if result.ephemeral:
        embed = build_result_embed(result)
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(embed=embed)
            except discord.HTTPException:
                pass
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    public_embed = _build_public_actor_embed(result, interaction.user.mention)
    if interaction.response.is_done():
        if interaction.channel is not None:
            await interaction.channel.send(embed=public_embed)
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        return

    await interaction.response.defer(ephemeral=True)
    if interaction.channel is not None:
        await interaction.channel.send(embed=public_embed)
    with suppress(discord.HTTPException):
        await interaction.delete_original_response()


async def complete_bound_result(
    interaction: discord.Interaction,
    *,
    bound_message: discord.InteractionMessage | None,
    result: DiscordCommandResult,
) -> None:
    """Finish one interactive form flow using its bound root message when available."""
    embed = build_result_embed(result)
    if bound_message is None:
        if interaction.response.is_done():
            if result.ephemeral:
                try:
                    await interaction.edit_original_response(embed=embed)
                except discord.HTTPException:
                    pass
            elif interaction.channel is not None:
                await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
        else:
            if result.ephemeral:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
                if interaction.channel is not None:
                    await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
                with suppress(discord.HTTPException):
                    await interaction.delete_original_response()
        return

    if result.ephemeral:
        if interaction.response.is_done():
            await bound_message.edit(embed=embed, view=None)
        else:
            await interaction.response.defer(ephemeral=True)
            await bound_message.edit(embed=embed, view=None)
        return

    with suppress(discord.HTTPException):
        await bound_message.edit(view=None)
    if interaction.response.is_done():
        if interaction.channel is not None:
            await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
    else:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel is not None:
            await interaction.channel.send(embed=_build_public_actor_embed(result, interaction.user.mention))
    with suppress(discord.HTTPException):
        await interaction.delete_original_response()
    with suppress(discord.HTTPException):
        await bound_message.delete()


def command_unavailable_result() -> DiscordCommandResult:
    """Build the shared error result used outside channel or DM contexts."""
    return Localizer.from_directory().result(
        "results.command_unavailable",
        language="english",
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
