"""Typed dispatch helpers for support ticket commands."""

from __future__ import annotations

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.commands import (
    AnswerSupportTicketCommand,
    CloseSupportTicketCommand,
    CreateSupportTicketCommand,
    ShowSupportTicketCommand,
)
from src.events.discord_results import DiscordCommandResult
from src.services.support_command_service import SupportTicketCreateResult, SupportTicketMessageResult, SupportTicketUpdateResult


async def dispatch_create_support_ticket(
    services: DiscordServiceBundle,
    command: CreateSupportTicketCommand,
) -> SupportTicketCreateResult:
    """Dispatch creation of a user-submitted support ticket."""
    return await services.support.handle_create(command)


async def dispatch_prepare_support_answer(
    services: DiscordServiceBundle,
    *,
    ticket_id: int,
    responder_id: int,
    subject: str,
    body: str,
) -> SupportTicketMessageResult:
    """Prepare the user-facing answer message for one support ticket."""
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
) -> SupportTicketUpdateResult:
    """Persist a support ticket as answered after the Discord send succeeds."""
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
) -> SupportTicketMessageResult:
    """Prepare the user-facing close message for one support ticket."""
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
) -> SupportTicketUpdateResult:
    """Persist a support ticket as closed after the Discord send succeeds."""
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
) -> DiscordCommandResult:
    """Dispatch a privileged show request for the ticket's source context."""
    return await services.support.handle_show(
        ShowSupportTicketCommand(
            ticket_id=ticket_id,
            requester_id=requester_id,
            sections=sections,
        )
    )
