from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import discord
import pytest

from src.entrypoints.discord.commands.show_commands import register_show_commands
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer


@dataclass
class FakeUIDataProvider:
    language: str = "german"

    def get_thread_language(self, _discord_channel_id: int) -> str:
        return self.language


@dataclass
class FakeResponse:
    sent_embed: discord.Embed | None = None
    sent_view: object | None = None
    ephemeral: bool | None = None

    async def send_message(self, *, embed: discord.Embed, view: object, ephemeral: bool) -> None:
        self.sent_embed = embed
        self.sent_view = view
        self.ephemeral = ephemeral


@dataclass
class FakeInteraction:
    channel_id: int = 100
    user: object = field(default_factory=lambda: SimpleNamespace(id=200))
    response: FakeResponse = field(default_factory=FakeResponse)

    async def original_response(self) -> object:
        return object()


@pytest.mark.asyncio
async def test_show_command_section_path_passes_item_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    captured: dict[str, object] = {}

    async def fake_dispatch(*_args, **_kwargs) -> DiscordCommandResult:
        return DiscordCommandResult(
            title="Show",
            message="**Pings**\n- one",
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    async def fake_ensure(*_args, **_kwargs) -> bool:
        return True

    class FakeView:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.bound_message = None

        def render_embed(self) -> discord.Embed:
            return discord.Embed(title="Show")

    monkeypatch.setattr(
        "src.entrypoints.discord.commands.show_commands.dispatch_show_configuration",
        fake_dispatch,
    )
    monkeypatch.setattr(
        "src.entrypoints.discord.commands.show_commands.ensure_ui_flow_allowed",
        fake_ensure,
    )
    monkeypatch.setattr(
        "src.entrypoints.discord.commands.show_commands.ShowPaginationView",
        FakeView,
    )

    register_show_commands(tree, services=object(), ui_data_provider=FakeUIDataProvider(), localizer=localizer)
    show_command = next(command for command in tree.get_commands() if command.name == "show")
    interaction = FakeInteraction()

    await show_command.callback(interaction, section=discord.app_commands.Choice(name="pings", value="pings"))

    assert captured["item_prefix"] == localizer.text("show.pattern.pagination.item_prefix", language="german")
    assert interaction.response.ephemeral is True
