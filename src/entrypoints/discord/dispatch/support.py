"""Typed dispatch helpers for support ticket commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import (
    AnswerSupportTicketCommand,
    CloseSupportTicketCommand,
    CreateSupportTicketCommand,
    ShowSupportTicketCommand,
)


async def dispatch_create_support_ticket(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int,
    requester_id: int,
    category: str,
    title: str,
    description: str,
    language_hint: str | None,
) -> object:
    return await services.support.handle_create(
        CreateSupportTicketCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            category=category,
            title=title,
            description=description,
            language_hint=language_hint,
        )
    )


async def dispatch_prepare_support_answer(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    responder_id: int,
    subject: str,
    body: str,
) -> object:
    return await services.support.prepare_answer(
        AnswerSupportTicketCommand(
            ticket_id=ticket_id,
            responder_id=responder_id,
            subject=subject,
            body=body,
        )
    )


async def dispatch_mark_support_answered(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    responder_id: int,
    subject: str,
    body: str,
) -> object:
    return await services.support.mark_answered(
        AnswerSupportTicketCommand(
            ticket_id=ticket_id,
            responder_id=responder_id,
            subject=subject,
            body=body,
        )
    )


async def dispatch_prepare_support_close(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    closer_id: int,
) -> object:
    return await services.support.prepare_close(
        CloseSupportTicketCommand(
            ticket_id=ticket_id,
            closer_id=closer_id,
        )
    )


async def dispatch_mark_support_closed(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    closer_id: int,
) -> object:
    return await services.support.mark_closed(
        CloseSupportTicketCommand(
            ticket_id=ticket_id,
            closer_id=closer_id,
        )
    )


async def dispatch_show_support_ticket_configuration(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    requester_id: int,
    sections: tuple[str, ...],
) -> object:
    return await services.support.handle_show(
        ShowSupportTicketCommand(
            ticket_id=ticket_id,
            requester_id=requester_id,
            sections=sections,
        )
    )
