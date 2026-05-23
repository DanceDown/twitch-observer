"""Twitch IRC entrypoint for normalized chat intake."""

from __future__ import annotations

import logging

from src.gateways.twitch_irc import AnonymousTwitchIRCGateway
from src.services.chat_pipeline import ChatMessageProcessingService

from .parser import build_chat_message_event, parse_irc_message

logger = logging.getLogger(__name__)


class TwitchIRCEntrypoint:
    """Consume raw IRC lines and forward normalized chat messages into the pipeline."""

    def __init__(
        self,
        gateway: AnonymousTwitchIRCGateway,
        *,
        message_processor: ChatMessageProcessingService | None = None,
    ) -> None:
        self._gateway = gateway
        self._message_processor = message_processor
        self._gateway.set_line_handler(self.handle_line)

    async def start(self) -> None:
        """Start the IRC gateway and consume incoming lines."""
        await self._gateway.start()

    async def stop(self) -> None:
        """Stop the underlying IRC gateway."""
        await self._gateway.stop()

    def set_message_processor(self, message_processor: ChatMessageProcessingService) -> None:
        """Bind the direct chat pipeline after runtime assembly."""
        self._message_processor = message_processor

    async def handle_line(self, raw_line: str) -> None:
        """Handle one raw IRC line."""
        message = parse_irc_message(raw_line)
        logger.debug("Received IRC line: %s", raw_line.strip())
        if message.command == "PING" and message.trailing:
            await self._gateway.send_pong(message.trailing)
            return

        event = build_chat_message_event(message)
        if event is None:
            return
        logger.debug(
            "Built Twitch chat event channel=%s author=%s broadcaster_id=%s message_id=%s content=%r",
            event.channel_login,
            event.author_login,
            event.broadcaster_id,
            event.message_id,
            event.content,
        )
        if self._message_processor is None:
            logger.warning("Dropping Twitch chat message because no chat pipeline is configured yet.")
            return
        await self._message_processor.process(event)

