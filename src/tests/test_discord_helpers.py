from __future__ import annotations

from src.adapters.discord.helpers import _build_public_actor_embed as build_command_public_actor_embed
from src.adapters.discord.ui.shared import _build_public_actor_embed as build_form_public_actor_embed
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer


def test_public_actor_embed_replaces_deferred_user_placeholder_without_duplicate_prefix() -> None:
    localizer = Localizer.from_directory()
    message = localizer._interpolate("{USER} added a ping: `{PING}`", {"PING": "alpha"})  # type: ignore[attr-defined]
    result = DiscordCommandResult(
        title="Ping Added",
        message=message,
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    for builder in (build_command_public_actor_embed, build_form_public_actor_embed):
        embed = builder(result, "@Tester")

        assert embed.description is not None
        assert embed.description.count("@Tester") == 1
        assert "{USER}" not in embed.description
        assert "`alpha`" in embed.description


def test_public_actor_embed_keeps_legacy_prefix_when_no_user_placeholder_exists() -> None:
    result = DiscordCommandResult(
        title="Ping Added",
        message="Added a ping.",
        style=DiscordResultStyle.SUCCESS,
        ephemeral=False,
    )

    for builder in (build_command_public_actor_embed, build_form_public_actor_embed):
        embed = builder(result, "@Tester")

        assert embed.description is not None
        assert embed.description.startswith("@Tester ")
        assert "Added a ping." in embed.description
