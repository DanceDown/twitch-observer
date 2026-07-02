from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import discord
import pytest

from src.entrypoints.discord.commands.help_commands import register_help_commands
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer


@dataclass
class FakeResponse:
    sent_embed: discord.Embed | None = None
    sent_view: object | None = None
    ephemeral: bool | None = None

    async def send_message(self, *, embed: discord.Embed, ephemeral: bool, view: object | None = None) -> None:
        self.sent_embed = embed
        self.sent_view = view
        self.ephemeral = ephemeral


@dataclass
class FakeInteraction:
    channel_id: int | None = None
    locale: str = "de"
    user: object = field(default_factory=lambda: SimpleNamespace(id=200))
    response: FakeResponse = field(default_factory=FakeResponse)

    async def original_response(self) -> object:
        return object()


@pytest.mark.asyncio
async def test_help_command_without_section_requests_overview(monkeypatch: pytest.MonkeyPatch) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    captured: dict[str, object] = {}

    async def fake_dispatch(*_args, **kwargs) -> DiscordCommandResult:
        captured.update(kwargs)
        return DiscordCommandResult(
            title="Hilfe",
            message="Short help",
            style=DiscordResultStyle.INFO,
            ephemeral=True,
            language="german",
        )

    async def fake_send_initial_result(_interaction: object, result: DiscordCommandResult) -> None:
        captured["sent_result"] = result

    monkeypatch.setattr("src.entrypoints.discord.commands.help_commands.dispatch_help", fake_dispatch)
    monkeypatch.setattr("src.entrypoints.discord.commands.help_commands.send_initial_result", fake_send_initial_result)

    register_help_commands(tree, services=object(), ui_data_provider=object(), localizer=localizer)
    help_command = next(command for command in tree.get_commands() if command.name == "help")

    assert help_command.parameters[0].required is False

    await help_command.callback(FakeInteraction(), section=None)

    assert captured["section"] is None
    assert isinstance(captured["sent_result"], DiscordCommandResult)


@pytest.mark.asyncio
async def test_help_command_uses_paginator_for_multi_page_help(monkeypatch: pytest.MonkeyPatch) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    captured: dict[str, object] = {}

    async def fake_dispatch(*_args, **_kwargs) -> DiscordCommandResult:
        return DiscordCommandResult(
            title="Hilfe",
            message="**Tips**\n- one",
            style=DiscordResultStyle.INFO,
            ephemeral=True,
            language="german",
        )

    def fake_build_pages(*_args, **_kwargs) -> tuple[str, ...]:
        return ("page 1", "page 2")

    class FakeView:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.bound_message = None

        def render_embed(self) -> discord.Embed:
            return discord.Embed(title="Help")

    monkeypatch.setattr("src.entrypoints.discord.commands.help_commands.dispatch_help", fake_dispatch)
    monkeypatch.setattr("src.entrypoints.discord.commands.help_commands.build_show_pages", fake_build_pages)
    monkeypatch.setattr("src.entrypoints.discord.commands.help_commands.ShowPaginationView", FakeView)

    register_help_commands(tree, services=object(), ui_data_provider=object(), localizer=localizer)
    help_command = next(command for command in tree.get_commands() if command.name == "help")
    interaction = FakeInteraction()

    await help_command.callback(
        interaction,
        section=discord.app_commands.Choice(name="tips", value="tips"),
    )

    assert captured["item_prefix"] == "- "
    assert interaction.response.ephemeral is True
