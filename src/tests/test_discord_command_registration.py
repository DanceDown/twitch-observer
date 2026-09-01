from __future__ import annotations

import discord
import pytest

from src.entrypoints.discord.commands import (
    register_account_commands,
    register_channel_commands,
    register_live_state_commands,
    register_pattern_commands,
    register_permission_commands,
    register_reply_commands,
    register_user_commands,
)
from src.entrypoints.discord.commands.localized import CommandCatalogTranslator, command_text
from src.localization import Localizer


def test_action_commands_remove_open_subcommands_and_make_ui_entry_fields_optional() -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()

    register_channel_commands(tree, object(), object(), localizer)
    register_user_commands(tree, object(), object(), localizer)
    register_pattern_commands(tree, object(), object(), localizer)
    register_reply_commands(tree, object(), object(), localizer)
    register_live_state_commands(tree, object(), object(), localizer)
    register_permission_commands(tree, object(), object(), localizer)
    register_account_commands(tree, object(), object(), localizer)

    command_names = {command.name for command in tree.get_commands()}
    assert {"channel", "user", "ping", "reply", "liveping", "permission", "account"} <= command_names
    assert "offlineping" not in command_names

    channel_group = _group_command(tree, "channel")
    assert [command.name for command in channel_group.commands] == ["add", "remove", "color"]
    assert not _subcommand(channel_group, "add").parameters[0].required
    assert not _subcommand(channel_group, "remove").parameters[0].required
    assert not _subcommand(channel_group, "color").parameters[0].required

    user_group = _group_command(tree, "user")
    assert [command.name for command in user_group.commands] == ["add", "remove"]
    assert not _subcommand(user_group, "add").parameters[0].required
    assert not _subcommand(user_group, "remove").parameters[0].required

    ping_group = _group_command(tree, "ping")
    assert "open" not in {command.name for command in ping_group.commands}
    assert not _subcommand(ping_group, "add").parameters[0].required
    assert not _subcommand(ping_group, "edit").parameters[0].required
    assert not _subcommand(ping_group, "remove").parameters[0].required
    assert not _subcommand(ping_group, "disable").parameters[0].required
    assert not _subcommand(ping_group, "enable").parameters[0].required

    reply_group = _group_command(tree, "reply")
    assert {command.name for command in reply_group.commands} == {"pattern", "event"}
    reply_pattern_group = _subgroup(reply_group, "pattern")
    assert not _subcommand(reply_pattern_group, "add").parameters[0].required
    assert not _subcommand(reply_pattern_group, "add").parameters[1].required
    assert not _subcommand(reply_pattern_group, "remove").parameters[0].required
    reply_event_group = _subgroup(reply_group, "event")
    assert not _subcommand(reply_event_group, "add").parameters[0].required
    assert not _subcommand(reply_event_group, "add").parameters[1].required
    assert not _subcommand(reply_event_group, "remove").parameters[0].required

    liveping_group = _group_command(tree, "liveping")
    assert [command.name for command in liveping_group.commands] == ["add", "remove", "color"]
    assert [parameter.name for parameter in _subcommand(liveping_group, "add").parameters] == [
        "twitch_channel_login",
        "state",
    ]
    assert [parameter.name for parameter in _subcommand(liveping_group, "remove").parameters] == ["ping_id"]
    assert [parameter.name for parameter in _subcommand(liveping_group, "color").parameters] == ["ping_id", "color"]
    assert all(not parameter.required for parameter in _subcommand(liveping_group, "add").parameters)
    assert all(not parameter.required for parameter in _subcommand(liveping_group, "remove").parameters)
    assert all(not parameter.required for parameter in _subcommand(liveping_group, "color").parameters)

    permission_group = _group_command(tree, "permission")
    assert "open" not in {command.name for command in permission_group.commands}
    assert not _subcommand(permission_group, "grant").parameters[0].required
    assert not _subcommand(permission_group, "grant").parameters[1].required
    assert not _subcommand(permission_group, "revoke").parameters[0].required
    assert not _subcommand(permission_group, "revoke").parameters[1].required
    assert not _subcommand(permission_group, "clear").parameters[0].required

    account_group = _group_command(tree, "account")
    assert [command.name for command in account_group.commands] == ["connect", "disconnect"]


@pytest.mark.asyncio
async def test_command_catalog_translator_uses_german_command_metadata() -> None:
    localizer = Localizer.from_directory()
    translator = CommandCatalogTranslator(localizer)
    text = command_text(localizer, "support.description")

    assert str(text) == localizer.text("discord.commands.support.description", language="english")
    assert await translator.translate(text, discord.Locale.american_english, object()) is None
    assert await translator.translate(text, discord.Locale.german, object()) == localizer.text(
        "discord.commands.support.description",
        language="german",
    )


def _group_command(
    tree: discord.app_commands.CommandTree,
    name: str,
) -> discord.app_commands.Group:
    for command in tree.get_commands():
        if command.name == name:
            assert isinstance(command, discord.app_commands.Group)
            return command
    raise AssertionError(f"Missing command group: {name}")


def _subcommand(group: discord.app_commands.Group, name: str) -> discord.app_commands.Command:
    for command in group.commands:
        if command.name == name:
            assert isinstance(command, discord.app_commands.Command)
            return command
    raise AssertionError(f"Missing subcommand: {group.name} {name}")


def _subgroup(group: discord.app_commands.Group, name: str) -> discord.app_commands.Group:
    for command in group.commands:
        if command.name == name:
            assert isinstance(command, discord.app_commands.Group)
            return command
    raise AssertionError(f"Missing subgroup: {group.name} {name}")
