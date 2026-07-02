from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.database.records import ThreadRecord
from src.entrypoints.discord.dispatch import dispatch_help
from src.events.commands import HelpCommand
from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.help_service import HelpCommandService
from src.tests.dispatch_helpers import make_services


@dataclass
class FakeThreadRepository:
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)


@dataclass
class FakeHelpService:
    seen: list[HelpCommand] = field(default_factory=list)

    async def handle_command(self, command: HelpCommand) -> object:
        self.seen.append(command)
        return SimpleNamespace(style=DiscordResultStyle.INFO, message="ok")


@pytest.mark.asyncio
async def test_help_service_prefers_thread_language_for_specific_section() -> None:
    service = HelpCommandService(
        thread_repository=FakeThreadRepository(
            threads_by_channel_id={
                100: ThreadRecord(
                    thread_id=1,
                    owner_id=200,
                    discord_channel_id=100,
                    enabled=True,
                    color=None,
                    language="german",
                )
            }
        ),
        localizer=Localizer.from_directory(),
    )

    result = await service.handle_command(
        HelpCommand(
            discord_channel_id=100,
            requester_id=200,
            language_hint="english",
            section="pings",
        )
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert result.language == "german"
    assert "/ping" in result.message


@pytest.mark.asyncio
async def test_help_service_falls_back_to_overview_and_language_hint() -> None:
    service = HelpCommandService(
        thread_repository=FakeThreadRepository(),
        localizer=Localizer.from_directory(),
    )

    result = await service.handle_command(
        HelpCommand(
            discord_channel_id=999,
            requester_id=200,
            language_hint="english",
            section="unknown_topic",
        )
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert result.language == "english"
    assert "/join" in result.message
    assert "/channel" in result.message


@pytest.mark.asyncio
async def test_help_service_renders_regex_focused_tips_section() -> None:
    service = HelpCommandService(
        thread_repository=FakeThreadRepository(),
        localizer=Localizer.from_directory(),
    )

    result = await service.handle_command(
        HelpCommand(
            discord_channel_id=None,
            requester_id=200,
            language_hint="english",
            section="tips",
        )
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert ".*" in result.message
    assert "^Your text$" in result.message
    assert "^!song$" in result.message
    assert "hello|hi|hey" in result.message
    assert "\\bword\\b" in result.message


@pytest.mark.asyncio
async def test_help_dispatch_calls_help_service_directly() -> None:
    help_service = FakeHelpService()
    services = make_services(help=help_service)

    result = await dispatch_help(
        services,
        discord_channel_id=100,
        requester_id=200,
        language_hint="german",
        section="tips",
    )

    assert result.style is DiscordResultStyle.INFO
    assert help_service.seen == [
        HelpCommand(
            discord_channel_id=100,
            requester_id=200,
            language_hint="german",
            section="tips",
        )
    ]
