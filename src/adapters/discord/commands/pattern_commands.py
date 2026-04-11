from __future__ import annotations

"""Slash-command registration for the unified `/ping` command group."""

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_pattern_command, dispatch_pattern_edit_command
from ..helpers import command_unavailable_result, normalize_optional_text, send_initial_result, split_csv_values

logger = logging.getLogger(__name__)


def register_pattern_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    """Register the `/ping` group on the shared command tree."""
    ping_group = app_commands.Group(
        name="ping",
        description="Manage tracking rules. Set `is_regex` when the rule should use regex syntax.",
    )

    @ping_group.command(name="add", description="Add a new ping rule or regex rule.")
    @app_commands.describe(
        text="The word, phrase, or regex that should trigger a notification.",
        is_regex="Whether the text should be treated as a regex instead of a normal ping.",
        channel_scope="How the selected channels should be interpreted.",
        channels="Optional comma-separated tracked Twitch channel logins for the selected scope.",
        user_scope="How the selected users should be interpreted.",
        users="Optional comma-separated Twitch user logins for the selected scope.",
        sub_state="Whether the sender must be subscribed.",
        offline_state="Whether the target channel must be online or offline.",
        case_sensitive="Whether matching should respect casing.",
        color="Optional embed color in #RRGGBB.",
    )
    @app_commands.choices(
        channel_scope=[
            app_commands.Choice(name="all tracked channels", value="all_tracked"),
            app_commands.Choice(name="only selected channels", value="only_selected"),
            app_commands.Choice(name="all except selected channels", value="all_except_selected"),
        ],
        user_scope=[
            app_commands.Choice(name="all users", value="all_users"),
            app_commands.Choice(name="only selected users", value="only_selected"),
            app_commands.Choice(name="all except selected users", value="all_except_selected"),
        ],
        sub_state=[
            app_commands.Choice(name="everyone", value="all"),
            app_commands.Choice(name="subs only", value="subs"),
            app_commands.Choice(name="non-subs only", value="non_subs"),
        ],
        offline_state=[
            app_commands.Choice(name="online or offline", value="both"),
            app_commands.Choice(name="only while online", value="online"),
            app_commands.Choice(name="only while offline", value="offline"),
        ],
    )
    async def ping_add(
        interaction: discord.Interaction,
        text: str,
        is_regex: bool = False,
        channel_scope: str = "all_tracked",
        channels: str | None = None,
        user_scope: str = "all_users",
        users: str | None = None,
        sub_state: str = "all",
        offline_state: str = "both",
        case_sensitive: bool = False,
        color: str | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord ping add discord_channel_id=%s requester_id=%s is_regex=%s text=%r channel_scope=%s channels=%r user_scope=%s users=%r sub=%s offline=%s case_sensitive=%s color=%r",
            interaction.channel_id,
            interaction.user.id,
            is_regex,
            text,
            channel_scope,
            channels,
            user_scope,
            users,
            sub_state,
            offline_state,
            case_sensitive,
            color,
        )
        result = await dispatch_pattern_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action="add",
            pattern_text=text,
            pattern_id=None,
            is_regex=is_regex,
            channel_scope_mode=channel_scope,
            twitch_channel_logins=split_csv_values(channels),
            user_scope_mode=user_scope,
            twitch_user_logins=split_csv_values(users),
            sub_state=sub_state,
            offline_state=offline_state,
            case_sensitive=case_sensitive,
            color=normalize_optional_text(color),
            disabled=False,
        )
        await send_initial_result(interaction, result)

    _register_id_command(ping_group, event_bus=event_bus, name="remove", action="remove")
    _register_id_command(ping_group, event_bus=event_bus, name="disable", action="disable")
    _register_id_command(ping_group, event_bus=event_bus, name="enable", action="enable")

    @ping_group.command(name="edit", description="Edit an existing ping or regex rule.")
    @app_commands.describe(
        id="The stable rule ID shown by /show.",
        text="Optional new ping or regex text.",
        is_regex="Optionally switch between normal ping mode and regex mode.",
        channel_scope="Optional new channel scope.",
        channels="Optional comma-separated tracked Twitch channel logins for the selected scope.",
        user_scope="Optional new user scope.",
        users="Optional comma-separated Twitch user logins for the selected scope.",
        sub_state="Optional new subscriber filter.",
        offline_state="Optional new online/offline filter.",
        case_sensitive="Optionally change case sensitivity.",
        color="Optional new embed color in #RRGGBB.",
        clear_color="Remove a previously stored custom color.",
        priority="Optional manual priority from 0 to 9.",
    )
    @app_commands.choices(
        channel_scope=[
            app_commands.Choice(name="all tracked channels", value="all_tracked"),
            app_commands.Choice(name="only selected channels", value="only_selected"),
            app_commands.Choice(name="all except selected channels", value="all_except_selected"),
        ],
        user_scope=[
            app_commands.Choice(name="all users", value="all_users"),
            app_commands.Choice(name="only selected users", value="only_selected"),
            app_commands.Choice(name="all except selected users", value="all_except_selected"),
        ],
        sub_state=[
            app_commands.Choice(name="everyone", value="all"),
            app_commands.Choice(name="subs only", value="subs"),
            app_commands.Choice(name="non-subs only", value="non_subs"),
        ],
        offline_state=[
            app_commands.Choice(name="online or offline", value="both"),
            app_commands.Choice(name="only while online", value="online"),
            app_commands.Choice(name="only while offline", value="offline"),
        ],
    )
    async def ping_edit(
        interaction: discord.Interaction,
        id: int,
        text: str | None = None,
        is_regex: bool | None = None,
        channel_scope: str | None = None,
        channels: str | None = None,
        user_scope: str | None = None,
        users: str | None = None,
        sub_state: str | None = None,
        offline_state: str | None = None,
        case_sensitive: bool | None = None,
        color: str | None = None,
        clear_color: bool = False,
        priority: app_commands.Range[int, 0, 9] | None = None,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord ping edit discord_channel_id=%s requester_id=%s pattern_id=%s is_regex=%s channel_scope=%s user_scope=%s priority=%s",
            interaction.channel_id,
            interaction.user.id,
            id,
            is_regex,
            channel_scope,
            user_scope,
            priority,
        )
        result = await dispatch_pattern_edit_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            pattern_id=id,
            pattern_text=normalize_optional_text(text),
            is_regex=is_regex,
            channel_scope_mode=channel_scope,
            twitch_channel_logins=None if channels is None else split_csv_values(channels),
            user_scope_mode=user_scope,
            twitch_user_logins=None if users is None else split_csv_values(users),
            sub_state=sub_state,
            offline_state=offline_state,
            case_sensitive=case_sensitive,
            color=normalize_optional_text(color),
            clear_color=clear_color,
            priority=priority,
        )
        await send_initial_result(interaction, result)

    tree.add_command(ping_group)


def _register_id_command(
    group: app_commands.Group,
    *,
    event_bus: EventBus,
    name: str,
    action: str,
) -> None:
    """Register an ID-based ping subcommand like remove, disable, or enable."""

    @group.command(name=name, description=f"{name.capitalize()} an existing ping or regex rule by ID.")
    @app_commands.describe(id="The stable rule ID shown by /show.")
    async def id_command(interaction: discord.Interaction, id: int) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord ping %s discord_channel_id=%s requester_id=%s pattern_id=%s",
            action,
            interaction.channel_id,
            interaction.user.id,
            id,
        )
        result = await dispatch_pattern_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action=action,
            pattern_text=None,
            pattern_id=id,
            is_regex=None,
            channel_scope_mode="all_tracked",
            twitch_channel_logins=(),
            user_scope_mode="all_users",
            twitch_user_logins=(),
            sub_state="all",
            offline_state="both",
            case_sensitive=False,
            color=None,
            disabled=(action == "disable"),
        )
        await send_initial_result(interaction, result)
