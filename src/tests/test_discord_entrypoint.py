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


class _RaisingTrackingClient:
    def is_ready(self) -> bool:
        return True

    async def send_tracking_embed(
        self,
        discord_channel_id: int,
        embed,
        *,
        channel_login: str | None = None,
        thread_id: int | None = None,
    ) -> None:
        _ = discord_channel_id, embed, channel_login, thread_id
        raise aiohttp.ServerDisconnectedError()


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


@pytest.mark.asyncio
async def test_discord_entrypoint_ignores_tracking_update_during_transient_disconnect() -> None:
    entrypoint = object.__new__(DiscordEntrypoint)
    entrypoint._config = SimpleNamespace(discord_bot_token="token")
    entrypoint._client = _RaisingTrackingClient()

    await entrypoint.send_tracking_embed(123, object())
