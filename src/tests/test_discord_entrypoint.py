from __future__ import annotations

from types import SimpleNamespace

import aiohttp
import pytest

from src.entrypoints.discord.entrypoint import DiscordEntrypoint


class _RaisingPresenceClient:
    def is_ready(self) -> bool:
        return True

    async def set_status_text(self, text: str) -> None:
        _ = text
        raise aiohttp.ClientConnectionResetError("Cannot write to closing transport")


class _RecordingPresenceClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_ready(self) -> bool:
        return True

    async def set_status_text(self, text: str) -> None:
        self.calls.append(text)


@pytest.mark.asyncio
async def test_discord_entrypoint_ignores_presence_update_during_reconnect() -> None:
    entrypoint = object.__new__(DiscordEntrypoint)
    entrypoint._config = SimpleNamespace(discord_bot_token="token")
    entrypoint._client = _RaisingPresenceClient()

    await entrypoint.set_status_text("hello")


@pytest.mark.asyncio
async def test_discord_entrypoint_updates_presence_when_client_is_ready() -> None:
    client = _RecordingPresenceClient()
    entrypoint = object.__new__(DiscordEntrypoint)
    entrypoint._config = SimpleNamespace(discord_bot_token="token")
    entrypoint._client = client

    await entrypoint.set_status_text("hello")

    assert client.calls == ["hello"]
