from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.entrypoints.discord.dispatch import dispatch_join_thread, dispatch_ui_flow_decision
from src.events.discord_results import DiscordResultStyle
from src.events.ui_flow import DiscordUIFlowDecision, RequestUIFlowCommand, UIFlowKind, UIFlowStep
from src.tests.dispatch_helpers import make_services


@dataclass
class FakeThreadService:
    calls: list[tuple[int, int]]

    async def handle_join(self, command) -> object:
        self.calls.append((command.discord_channel_id, command.requester_id))
        return type("Result", (), {"style": DiscordResultStyle.SUCCESS, "message": "ok"})()


@dataclass
class FakeUIFlowGuard:
    seen: list[RequestUIFlowCommand]

    async def decide(self, command: RequestUIFlowCommand) -> DiscordUIFlowDecision:
        self.seen.append(command)
        return DiscordUIFlowDecision(flow=command.flow, step=command.step, open_ui=True)


@pytest.mark.asyncio
async def test_command_dispatch_calls_thread_service_directly() -> None:
    thread = FakeThreadService(calls=[])
    services = make_services(thread=thread)

    result = await dispatch_join_thread(services, discord_channel_id=100, requester_id=200)

    assert result.style is DiscordResultStyle.SUCCESS
    assert thread.calls == [(100, 200)]


@pytest.mark.asyncio
async def test_ui_flow_dispatch_calls_guard_service_directly() -> None:
    guard = FakeUIFlowGuard(seen=[])
    services = make_services(ui_flow_guard=guard)

    decision = await dispatch_ui_flow_decision(
        services,
        discord_channel_id=100,
        requester_id=200,
        flow=UIFlowKind.CHANNEL,
        step=UIFlowStep.ROOT,
    )

    assert decision.open_ui is True
    assert guard.seen == [
        RequestUIFlowCommand(
            discord_channel_id=100,
            requester_id=200,
            flow=UIFlowKind.CHANNEL,
            step=UIFlowStep.ROOT,
        )
    ]
