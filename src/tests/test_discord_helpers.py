from __future__ import annotations

from src.entrypoints.discord.helpers import build_public_result_embed
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer


def test_public_actor_embed_keeps_direct_user_placeholder_without_duplicate_prefix() -> None:
    localizer = Localizer.from_directory()
    message = localizer._interpolate(  # type: ignore[attr-defined]
        "{RAW:USER} added a ping: `{PING}`",
        {"USER": "@Tester", "PING": "alpha"},
    )
    result = DiscordCommandResult(
        title="Ping Added",
        message=message,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    embed = build_public_result_embed(result)

    assert embed.description is not None
    assert embed.description.count("@Tester") == 1
    assert "`alpha`" in embed.description


def test_public_actor_embed_keeps_plain_body_when_no_user_placeholder_exists() -> None:
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    embed = build_public_result_embed(result)

    assert embed.description is not None
    assert embed.description == "Added a ping."
