"""Retry-aware Discord delivery helpers for result and audit embeds."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp
import discord

from src.config import get_discord_delivery_max_attempts

logger = logging.getLogger(__name__)

DISCORD_RATE_LIMIT_STATUS = 429
DISCORD_SERVER_ERROR_MIN_STATUS = 500


@dataclass(slots=True, frozen=True)
class DiscordEmbedSendRequest:
    """All options needed to send one Discord embed with retry handling."""

    embed: discord.Embed
    purpose: str
    max_attempts: int | None = None
    view: discord.ui.View | None = None
    allowed_mentions: discord.AllowedMentions | None = None


async def send_embed_with_retries(
    channel: discord.abc.Messageable,
    *,
    request: DiscordEmbedSendRequest,
) -> bool:
    """Send one embed and retry only when Discord likely failed transiently."""
    sent, _message = await _send_embed_with_retries(
        channel,
        request=request,
    )
    return sent


async def send_embed_message_with_retries(
    channel: discord.abc.Messageable,
    *,
    request: DiscordEmbedSendRequest,
) -> discord.Message | None:
    """Send one embed and return the created message when delivery succeeds."""
    sent, message = await _send_embed_with_retries(
        channel,
        request=request,
    )
    return message if sent else None


async def _send_embed_with_retries(
    channel: discord.abc.Messageable,
    *,
    request: DiscordEmbedSendRequest,
) -> tuple[bool, discord.Message | None]:
    """Send one embed and report both delivery success and the Discord message."""
    configured_max_attempts = get_discord_delivery_max_attempts() if request.max_attempts is None else max(1, request.max_attempts)
    channel_id = getattr(channel, "id", None)
    for attempt in range(1, configured_max_attempts + 1):
        try:
            send_kwargs: dict[str, object] = {"embed": request.embed}
            if request.view is not None:
                send_kwargs["view"] = request.view
            if request.allowed_mentions is not None:
                send_kwargs["allowed_mentions"] = request.allowed_mentions
            message = await channel.send(**send_kwargs)
            if attempt > 1:
                logger.info(
                    "Discord %s send succeeded on retry attempt %s/%s channel_id=%s.",
                    request.purpose,
                    attempt,
                    configured_max_attempts,
                    channel_id,
                )
            return True, message
        except (discord.Forbidden, discord.NotFound):
            raise
        except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError) as error:
            if not _is_retryable_send_error(error) or attempt >= configured_max_attempts:
                logger.exception(
                    "Discord %s send failed after %s attempt(s) channel_id=%s.",
                    request.purpose,
                    attempt,
                    channel_id,
                )
                return False, None
            delay_seconds = float(attempt)
            logger.warning(
                "Discord %s send failed on attempt %s/%s channel_id=%s; retrying in %.1fs: %s",
                request.purpose,
                attempt,
                configured_max_attempts,
                channel_id,
                delay_seconds,
                error,
            )
            await asyncio.sleep(delay_seconds)
    return False, None


def _is_retryable_send_error(error: Exception) -> bool:
    """Return whether one Discord send error is likely transient."""
    if isinstance(error, aiohttp.ClientError | TimeoutError | OSError):
        return True
    if isinstance(error, discord.HTTPException):
        status = getattr(error, "status", None)
        return status is None or status == DISCORD_RATE_LIMIT_STATUS or status >= DISCORD_SERVER_ERROR_MIN_STATUS
    return False
