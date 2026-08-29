"""Shared Discord entrypoint helpers for command handlers and modals."""

from __future__ import annotations

from contextlib import suppress
import logging

import discord

from src.discord_results import build_result
from src.entrypoints.discord.delivery import send_embed_with_retries
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.ui_flow import UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed
from src.entrypoints.discord.service_bundle import DiscordServiceBundle

from .dispatch import dispatch_ui_flow_decision

logger = logging.getLogger(__name__)


def build_public_result_embed(result: DiscordCommandResult) -> discord.Embed:
    """Render one public result embed without additional body rewriting."""
    return build_result_embed(result)


async def defer_interaction_response(
    interaction: discord.Interaction,
    *,
    ephemeral: bool = False,
) -> bool:
    """Try to acknowledge one interaction without crashing on expired tokens."""
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.HTTPException as error:
        if _is_unknown_interaction_error(error):
            logger.warning("Discord interaction expired before defer; continuing with fallback handling.")
            return False
        raise


async def send_message_response(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    ephemeral: bool,
    view: discord.ui.View | None = None,
) -> bool:
    """Try to send one interaction message response without crashing on expired tokens."""
    if interaction.response.is_done():
        return False
    try:
        send_kwargs: dict[str, object] = {
            "embed": embed,
            "ephemeral": ephemeral,
        }
        if view is not None:
            send_kwargs["view"] = view
        await interaction.response.send_message(**send_kwargs)
        return True
    except discord.HTTPException as error:
        if _is_unknown_interaction_error(error):
            logger.warning("Discord interaction expired before send_message; continuing with fallback handling.")
            return False
        raise


async def edit_original_response(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
) -> discord.InteractionMessage | None:
    """Try to edit one acknowledged interaction response without crashing on expired tokens."""
    try:
        edit_kwargs: dict[str, object] = {"embed": embed}
        if view is not None:
            edit_kwargs["view"] = view
        return await interaction.edit_original_response(**edit_kwargs)
    except discord.HTTPException as error:
        if _is_unknown_interaction_error(error):
            logger.warning("Discord interaction expired before edit_original_response; skipping edit.")
            return None
        raise


async def send_modal_response(interaction: discord.Interaction, modal: discord.ui.Modal) -> bool:
    """Try to open one modal without crashing on expired interaction tokens."""
    if interaction.response.is_done():
        return False
    try:
        await interaction.response.send_modal(modal)
        return True
    except discord.HTTPException as error:
        if _is_unknown_interaction_error(error):
            logger.warning("Discord interaction expired before send_modal; skipping modal open.")
            return False
        raise


async def send_initial_result(interaction: discord.Interaction, result: DiscordCommandResult) -> None:
    """Send the standardized embed response for a completed interaction."""
    if result.ephemeral:
        embed = build_result_embed(result)
        if interaction.response.is_done():
            with suppress(discord.HTTPException):
                await interaction.edit_original_response(embed=embed)
            return
        await send_message_response(interaction, embed=embed, ephemeral=True)
        return

    public_embed = build_public_result_embed(result)
    response_ready = interaction.response.is_done() or await defer_interaction_response(interaction, ephemeral=True)
    public_sent = False
    if interaction.channel is not None:
        try:
            public_sent = await send_embed_with_retries(
                interaction.channel,
                embed=public_embed,
                purpose="public interaction result",
            )
        except discord.Forbidden:
            if response_ready:
                fallback_embed = build_result_embed(_missing_channel_access_result(interaction))
                with suppress(discord.HTTPException):
                    await interaction.edit_original_response(embed=fallback_embed)
            return
        except discord.NotFound:
            logger.warning(
                "Discord channel disappeared before one public interaction result could be sent channel_id=%s.",
                interaction.channel_id,
            )
    if public_sent:
        if response_ready:
            with suppress(discord.HTTPException):
                await interaction.delete_original_response()
        return
    if response_ready:
        with suppress(discord.HTTPException):
            await interaction.edit_original_response(embed=public_embed)


async def complete_bound_result(
    interaction: discord.Interaction,
    *,
    bound_message: discord.InteractionMessage | None,
    result: DiscordCommandResult,
) -> None:
    """Finish one interactive form flow using its bound root message when available."""
    if bound_message is None:
        await send_initial_result(interaction, result)
        return

    embed = build_result_embed(result)
    if result.ephemeral:
        await defer_interaction_response(interaction, ephemeral=True)
        await bound_message.edit(embed=embed, view=None)
        return

    with suppress(discord.HTTPException):
        await bound_message.edit(view=None)
    response_ready = interaction.response.is_done() or await defer_interaction_response(interaction, ephemeral=True)
    public_sent = False
    if interaction.channel is not None:
        try:
            public_sent = await send_embed_with_retries(
                interaction.channel,
                embed=build_public_result_embed(result),
                purpose="bound public interaction result",
            )
        except discord.Forbidden:
            fallback_embed = build_result_embed(_missing_channel_access_result(interaction))
            with suppress(discord.HTTPException):
                await bound_message.edit(embed=fallback_embed, view=None)
            return
        except discord.NotFound:
            logger.warning(
                "Discord channel disappeared before one bound public interaction result could be sent channel_id=%s.",
                interaction.channel_id,
            )
    if public_sent:
        if response_ready:
            with suppress(discord.HTTPException):
                await interaction.delete_original_response()
        with suppress(discord.HTTPException):
            await bound_message.delete()
        return
    with suppress(discord.HTTPException):
        await bound_message.edit(embed=embed, view=None)
    return


def _is_unknown_interaction_error(error: discord.HTTPException) -> bool:
    """Return whether Discord rejected the interaction because its token already expired."""
    return getattr(error, "code", None) == 10062


async def ensure_ui_flow_allowed(
    interaction: discord.Interaction,
    services: DiscordServiceBundle,
    *,
    flow: UIFlowKind,
    step: UIFlowStep,
    discord_channel_id: int | None = None,
) -> bool:
    """Render a service-owned guard result or allow the UI step to continue."""
    decision = await dispatch_ui_flow_decision(
        services,
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


def command_unavailable_result() -> DiscordCommandResult:
    """Build the shared error result used outside channel or DM contexts."""
    return build_result(
        Localizer.from_directory(),
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
    language = resolve_interaction_language(localizer, interaction)
    return build_result(
        localizer,
        "results.thread.missing_channel_access",
        language=language,
        style=DiscordResultStyle.ERROR,
        ephemeral=True,
    )


def resolve_interaction_language(localizer: Localizer, interaction: discord.Interaction) -> str:
    """Best-effort language selection from the user's Discord locale."""
    locale_value = str(interaction.locale).lower()
    if locale_value.startswith("de"):
        return "german"
    if locale_value.startswith("en"):
        return "english"
    return localizer.default_language
