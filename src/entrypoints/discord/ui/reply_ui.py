"""Discord UI for `/reply`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.events.event_types import DiscordCommandResult, DiscordResultStyle, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.services.twitch_runtime import TWITCH_SEND_MESSAGE_ACTION

from ..dispatch import (
    dispatch_add_channel_event_reply,
    dispatch_add_pattern_reply,
    dispatch_disable_channel_event_reply,
    dispatch_disable_pattern_reply,
    dispatch_enable_channel_event_reply,
    dispatch_enable_pattern_reply,
    dispatch_remove_channel_event_reply,
    dispatch_remove_pattern_reply,
)
from ..helpers import complete_bound_result, normalize_optional_text
from ..ui_data import (
    AdapterEventActionPresentation,
    AdapterEventPresentation,
    DiscordUIDataProvider,
    PatternPresentation,
    ReplyPresentation,
)
from .shared import BaseFormView, resolve_context_language


def _pattern_label(pattern: PatternPresentation, *, localizer: Localizer, language: str) -> str:
    fallback = localizer.text("discord.reply_ui.common.untitled_ping", language=language)
    return (pattern.pattern.regex or fallback)[:100]


def _reply_label(reply: ReplyPresentation) -> str:
    return reply.reply.reply_message[:100]


def _event_state_label(event_key: str, *, localizer: Localizer, language: str) -> str:
    return localizer.text(
        "discord.reply_ui.common.state_live" if event_key == "stream.online" else "discord.reply_ui.common.state_offline",
        language=language,
    )


def _adapter_event_label(event: AdapterEventPresentation, *, localizer: Localizer, language: str) -> str:
    return localizer.text(
        "discord.reply_ui.common.event_label",
        language=language,
        CHANNEL=event.channel.display_name,
        STATE=_event_state_label(event.event.event_key, localizer=localizer, language=language),
    )[:100]


def _encode_pattern_target(pattern_id: int) -> str:
    return f"pattern:{pattern_id}"


def _encode_adapter_event_target(event_id: int) -> str:
    return f"adapter_event:{event_id}"


def _decode_target(value: str) -> tuple[str, int]:
    target_type, raw_id = value.split(":", 1)
    return target_type, int(raw_id)


class PatternReplyAddModal(discord.ui.Modal):
    """Attach one reply to one existing pattern using a modal."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        patterns: list[PatternPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.reply_ui.pattern_add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.message = discord.ui.TextInput(
            label=localizer.text("discord.reply_ui.pattern_add.message_label", language=language),
            style=discord.TextStyle.paragraph,
            placeholder=localizer.text(
                "discord.reply_ui.pattern_add.message_placeholder",
                language=language,
                NAME=localizer.text("discord.reply_ui.common.example_name", language=language),
            ),
            required=True,
            max_length=500,
        )
        self.pattern = discord.ui.Label(
            text=localizer.text("discord.reply_ui.pattern_add.pattern_label", language=language),
            description=localizer.text("discord.reply_ui.pattern_add.pattern_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_pattern_label(pattern, localizer=localizer, language=language),
                        value=_encode_pattern_target(pattern.pattern.pattern_id),
                        description=localizer.text(
                            "discord.reply_ui.pattern_add.pattern_option_description",
                            language=language,
                            ID=pattern.display_index,
                            TYPE=localizer.text(
                                "discord.reply_ui.common.regex_type" if pattern.pattern.is_regex else "discord.reply_ui.common.ping_type",
                                language=language,
                            ),
                        ),
                    )
                    for pattern in patterns[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.mode = discord.ui.Label(
            text=localizer.text("discord.reply_ui.pattern_add.mode_label", language=language),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(
                        label=localizer.text("discord.reply_ui.pattern_add.mode_message", language=language),
                        value="message",
                        default=True,
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("discord.reply_ui.pattern_add.mode_reply", language=language),
                        value="reply",
                    ),
                ]
            ),
        )
        self.add_item(self.message)
        self.add_item(self.pattern)
        self.add_item(self.mode)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        _, pattern_id = _decode_target(self.pattern.component.values[0])
        result = await dispatch_add_pattern_reply(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            pattern_id=pattern_id,
            message=normalize_optional_text(self.message.value),
            reply_as_reply=self.mode.component.value == "reply",
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class EventReplyAddModal(discord.ui.Modal):
    """Attach one auto-reply to one configured external event trigger."""

    def __init__(
        self,
        *,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        adapter_events: list[AdapterEventPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.reply_ui.event_add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        self.message = discord.ui.TextInput(
            label=localizer.text("discord.reply_ui.event_add.message_label", language=language),
            style=discord.TextStyle.paragraph,
            placeholder=localizer.text(
                "discord.reply_ui.event_add.message_placeholder",
                language=language,
                CHANNEL=localizer.text("discord.reply_ui.common.example_channel", language=language),
                STATE=localizer.text("discord.reply_ui.common.example_state", language=language),
            ),
            required=True,
            max_length=500,
        )
        self.adapter_event = discord.ui.Label(
            text=localizer.text("discord.reply_ui.event_add.trigger_label", language=language),
            description=localizer.text("discord.reply_ui.event_add.trigger_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_adapter_event_label(event, localizer=localizer, language=language),
                        value=_encode_adapter_event_target(event.event.event_id),
                        description=localizer.text(
                            "discord.reply_ui.event_add.trigger_option_description",
                            language=language,
                            LOGIN=event.channel.login[:80],
                            STATE=_event_state_label(
                                event.event.event_key,
                                localizer=localizer,
                                language=language,
                            ).lower(),
                        ),
                    )
                    for event in adapter_events[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.message)
        self.add_item(self.adapter_event)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        _, adapter_event_id = _decode_target(self.adapter_event.component.values[0])
        result = await dispatch_add_channel_event_reply(
            self._services,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            adapter_event_id=adapter_event_id,
            message=normalize_optional_text(self.message.value),
            reply_as_reply=False,
        )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ReplyActionModal(discord.ui.Modal):
    """Enable, disable, or remove one existing reply action via a modal."""

    def __init__(
        self,
        *,
        title: str,
        services: DiscordServiceBundle,
        discord_channel_id: int,
        requester_id: int,
        action: str,
        replies: list[ReplyPresentation | AdapterEventActionPresentation],
        localizer: Localizer,
        language: str,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=title, timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._action = action
        self._bound_message = bound_message
        self.reply = discord.ui.Label(
            text=localizer.text("discord.reply_ui.action.reply_label", language=language),
            description=localizer.text("discord.reply_ui.action.reply_description", language=language),
            component=discord.ui.Select(
                options=[
                    discord.SelectOption(
                        label=_reply_label(reply),
                        value=_encode_pattern_target(reply.reply.pattern_id),
                        description=localizer.text(
                            "discord.reply_ui.action.linked_pattern_description",
                            language=language,
                            PATTERN=_pattern_label(reply.pattern, localizer=localizer, language=language),
                        ),
                    )
                    if isinstance(reply, ReplyPresentation)
                    else discord.SelectOption(
                        label=(
                            reply.action.message_template
                            or localizer.text("discord.reply_ui.common.untitled_event_action", language=language)
                        )[:100],
                        value=_encode_adapter_event_target(reply.event.event.event_id),
                        description=localizer.text(
                            "discord.reply_ui.action.linked_event_description",
                            language=language,
                            EVENT=_adapter_event_label(reply.event, localizer=localizer, language=language),
                        ),
                    )
                    for reply in replies[:25]
                ],
                min_values=1,
                max_values=1,
            ),
        )
        self.add_item(self.reply)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        target_type, identifier = _decode_target(self.reply.component.values[0])
        if target_type == "pattern":
            if self._action == "remove":
                result = await dispatch_remove_pattern_reply(
                    self._services,
                    discord_channel_id=self._discord_channel_id,
                    requester_id=self._requester_id,
                    pattern_id=identifier,
                )
            elif self._action == "disable":
                result = await dispatch_disable_pattern_reply(
                    self._services,
                    discord_channel_id=self._discord_channel_id,
                    requester_id=self._requester_id,
                    pattern_id=identifier,
                )
            else:
                result = await dispatch_enable_pattern_reply(
                    self._services,
                    discord_channel_id=self._discord_channel_id,
                    requester_id=self._requester_id,
                    pattern_id=identifier,
                )
        elif self._action == "remove":
            result = await dispatch_remove_channel_event_reply(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                adapter_event_id=identifier,
            )
        elif self._action == "disable":
            result = await dispatch_disable_channel_event_reply(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                adapter_event_id=identifier,
            )
        else:
            result = await dispatch_enable_channel_event_reply(
                self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=self._requester_id,
                adapter_event_id=identifier,
            )
        await complete_bound_result(interaction, bound_message=self._bound_message, result=result)


class ReplyMenuView(BaseFormView):
    """Root `/reply` flow with separate buttons for pattern and event actions."""

    def __init__(
        self,
        *,
        owner_id: int,
        services: DiscordServiceBundle,
        data_provider: DiscordUIDataProvider,
        discord_channel_id: int,
        localizer: Localizer,
    ) -> None:
        super().__init__(
            owner_id=owner_id,
            localizer=localizer,
            language=resolve_context_language(
                localizer=localizer,
                data_provider=data_provider,
                discord_channel_id=discord_channel_id,
            ),
        )
        self._services = services
        self._data_provider = data_provider
        self._discord_channel_id = discord_channel_id
        self.add_pattern.label = self.text("discord.reply_ui.actions.add_pattern")
        self.add_event.label = self.text("discord.reply_ui.actions.add_event")
        self.remove.label = self.text("discord.reply_ui.actions.remove")
        self.disable.label = self.text("discord.reply_ui.actions.disable")
        self.enable.label = self.text("discord.reply_ui.actions.enable")

    def render_embed(self) -> discord.Embed:
        return self.form_embed("discord.reply_ui.menu.title", "discord.reply_ui.menu.message")

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add_pattern(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.REPLY,
            step=UIFlowStep.ADD_PATTERN,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        patterns = await self._data_provider.list_patterns(self._discord_channel_id)
        if not patterns:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title=self.text("discord.reply_ui.errors.no_patterns.title"),
                    message=self.text("discord.reply_ui.errors.no_patterns.message"),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            PatternReplyAddModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                patterns=patterns,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.primary)
    async def add_event(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.REPLY,
            step=UIFlowStep.ADD_EVENT,
            discord_channel_id=self._discord_channel_id,
        ):
            return
        adapter_events = await self._data_provider.list_adapter_events(self._discord_channel_id)
        if not adapter_events:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title=self.text("discord.reply_ui.errors.no_event_triggers.title"),
                    message=self.text("discord.reply_ui.errors.no_event_triggers.message"),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            EventReplyAddModal(
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                adapter_events=adapter_events,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "remove")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def disable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "disable")

    @discord.ui.button(label="_", style=discord.ButtonStyle.secondary)
    async def enable(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._open_action_modal(interaction, "enable")

    async def _open_action_modal(self, interaction: discord.Interaction, action: str) -> None:
        if not await self.ensure_step_allowed(
            interaction,
            self._services,
            flow=UIFlowKind.REPLY,
            step={
                "remove": UIFlowStep.REMOVE,
                "disable": UIFlowStep.DISABLE,
                "enable": UIFlowStep.ENABLE,
            }[action],
            discord_channel_id=self._discord_channel_id,
        ):
            return
        replies = list(await self._data_provider.list_replies(self._discord_channel_id))
        replies.extend(
            item
            for item in await self._data_provider.list_adapter_event_actions(self._discord_channel_id)
            if item.action.action_type == TWITCH_SEND_MESSAGE_ACTION
        )
        if action == "disable":
            replies = [item for item in replies if not _is_reply_target_disabled(item)]
        elif action == "enable":
            replies = [item for item in replies if _is_reply_target_disabled(item)]
        if not replies:
            await self.finish_with_interaction(
                interaction,
                DiscordCommandResult(
                    title=self.text("discord.reply_ui.errors.no_replies.title"),
                    message=self.text("discord.reply_ui.errors.no_replies.message"),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )
            return
        await interaction.response.send_modal(
            ReplyActionModal(
                title=self.text(f"discord.reply_ui.action.{action}_title"),
                services=self._services,
                discord_channel_id=self._discord_channel_id,
                requester_id=interaction.user.id,
                action=action,
                replies=replies,
                localizer=self._localizer,
                language=self.language,
                bound_message=self.bound_message,
            )
        )


def _is_reply_target_disabled(reply: ReplyPresentation | AdapterEventActionPresentation) -> bool:
    if isinstance(reply, ReplyPresentation):
        return reply.reply.disabled
    return reply.action.disabled
