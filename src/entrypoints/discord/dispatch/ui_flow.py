"""Typed dispatch helpers for service-owned UI gate checks."""

from __future__ import annotations

from src.events.event_types import DiscordUIFlowDecision, RequestUIFlowCommand, UIFlowKind, UIFlowStep
from src.entrypoints.discord.service_bundle import DiscordServiceBundle


async def dispatch_ui_flow_decision(
    services: DiscordServiceBundle,
    *,
    discord_channel_id: int | None,
    requester_id: int,
    flow: UIFlowKind,
    step: UIFlowStep,
) -> DiscordUIFlowDecision:
    """Ask services whether a Discord UI step may be rendered."""
    return services.ui_flow_guard.decide(
        RequestUIFlowCommand(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            flow=flow,
            step=step,
        ),
    )
