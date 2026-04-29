"""Shared Discord adapter helpers for command handlers and modals."""

from __future__ import annotations

from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer, resolve_deferred_placeholders
from src.utils.discord_embeds import build_result_embed

from .dispatch import dispatch_ui_flow_decision


def build_public_result_embed(result: DiscordCommandResult, actor_mention: str) -> discord.Embed:
    """Render one public result embed that names the Discord user who triggered it."""
    embed = build_result_embed(result)
    rendered_message = resolve_deferred_placeholders(result.message, USER=actor_mention)
    if rendered_message == result.message:
        rendered_message = f"{actor_mention} {result.message}"
    embed.description = rendered_message
    return embed


def _build_public_actor_embed(result: DiscordCommandResult, actor_mention: str) -> discord.Embed:
    """Backward-compatible alias for public result embed rendering."""
    return build_public_result_embed(result, actor_mention)


async def send_initial_result(interaction: discord.Interaction, result: DiscordCommandResult) -> None:
    """Send the standardized embed response for a completed interaction."""
    if result.ephemeral:
        embed = build_result_embed(result)
        if interaction.response.is_done():
            with suppress(discord.HTTPException):
                await interaction.edit_original_response(embed=embed)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    public_embed = build_public_result_embed(result, interaction.user.mention)
    if interaction.response.is_done():
        if interaction.channel is not None:
            try:
                await interaction.channel.send(embed=public_embed)
            except discord.Forbidden:
                fallback_embed = build_result_embed(_missing_channel_access_result(interaction))
                with suppress(discord.HTTPException):
                    await interaction.edit_original_response(embed=fallback_embed)
                return
        with suppress(discord.HTTPException):
            await interaction.delete_original_response()
        return

    await interaction.response.defer(ephemeral=True)
    if interaction.channel is not None:
        try:
            await interaction.channel.send(embed=public_embed)
        except discord.Forbidden:
            fallback_embed = build_result_embed(_missing_channel_access_result(interaction))
            with suppress(discord.HTTPException):
                await interaction.edit_original_response(embed=fallback_embed)
            return
    with suppress(discord.HTTPException):
        await interaction.delete_original_response()


async def ensure_ui_flow_allowed(
    interaction: discord.Interaction,
    event_bus: EventBus,
    *,
    flow: str,
    step: str,
    discord_channel_id: int | None = None,
) -> bool:
    """Render a service-owned guard result or allow the UI step to continue."""
    decision = await dispatch_ui_flow_decision(
        event_bus,
        discord_channel_id=interaction.channel_id if discord_channel_id is None else discord_channel_id,
        requester_id=interaction.user.id,
        flow=flow,
        step=step,
    )
    if decision.open_ui:
        return True
    if decision.result is not None:
        await send_initial_result(interaction, decision.result)
    return False


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
                with suppress(discord.HTTPException):
                    await interaction.edit_original_response(embed=embed)
            elif interaction.channel is not None:
                await interaction.channel.send(embed=build_public_result_embed(result, interaction.user.mention))
        else:
            if result.ephemeral:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
                if interaction.channel is not None:
                    await interaction.channel.send(embed=build_public_result_embed(result, interaction.user.mention))
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
            await interaction.channel.send(embed=build_public_result_embed(result, interaction.user.mention))
    else:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel is not None:
            await interaction.channel.send(embed=build_public_result_embed(result, interaction.user.mention))
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


def _missing_channel_access_result(interaction: discord.Interaction) -> DiscordCommandResult:
    """Build one localized channel-access error result for public-send failures."""
    localizer = Localizer.from_directory()
    locale_value = str(interaction.locale).lower()
    if locale_value.startswith("de"):
        language = "german"
    elif locale_value.startswith("en"):
        language = "english"
    else:
        language = localizer.default_language
    return localizer.result(
        "results.thread.missing_channel_access",
        language=language,
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )

