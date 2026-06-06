"""Discord UI for `/reply`."""

from __future__ import annotations

import discord

from src.entrypoints.discord.service_bundle import DiscordServiceBundle
from src.localization import Localizer

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
    PatternPresentation,
    ReplyPresentation,
)
from .selects import window_with_included_items


def _pattern_label(pattern: PatternPresentation, *, localizer: Localizer, language: str, scope: str) -> str:
    fallback = localizer.text(f"{scope}.untitled_pattern", language=language)
    return (pattern.pattern.regex or fallback)[:100]


def _reply_label(reply: ReplyPresentation) -> str:
    return reply.reply.reply_message[:100]


def _event_state_label(event_key: str, *, localizer: Localizer, language: str, scope: str) -> str:
    state_key = "live" if event_key == "stream.online" else "offline"
    return localizer.text(f"{scope}.state.{state_key}", language=language)


def _adapter_event_label(event: AdapterEventPresentation, *, localizer: Localizer, language: str, scope: str) -> str:
    return localizer.text(
        f"{scope}.event_label",
        language=language,
        sources={
            "view": {
                "channel": event.channel.display_name,
                "state": _event_state_label(event.event.event_key, localizer=localizer, language=language, scope=scope),
            }
        },
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
        default_pattern_id: int | None = None,
        default_message: str | None = None,
        default_reply_as_reply: bool = False,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.reply_ui.pattern_add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        visible_patterns = window_with_included_items(
            patterns,
            key=lambda pattern: pattern.pattern.pattern_id,
            included_keys=[default_pattern_id] if default_pattern_id is not None else [],
        )
        self.message = discord.ui.TextInput(
            label=localizer.text("discord.reply_ui.pattern_add.message_label", language=language),
            style=discord.TextStyle.paragraph,
            default=default_message,
            placeholder=localizer.text(
                "discord.reply_ui.pattern_add.message_placeholder",
                language=language,
                sources={"view": {"example_name": localizer.text("discord.reply_ui.pattern_add.example_name", language=language)}},
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
                        label=_pattern_label(
                            pattern,
                            localizer=localizer,
                            language=language,
                            scope="discord.reply_ui.pattern_add",
                        ),
                        value=_encode_pattern_target(pattern.pattern.pattern_id),
                        default=pattern.pattern.pattern_id == default_pattern_id,
                        description=localizer.text(
                            "discord.reply_ui.pattern_add.pattern_option_description",
                            language=language,
                            sources={
                                "view": {
                                    "display_id": pattern.display_index,
                                    "ping_mode": localizer.text(
                                        "discord.pattern_ui.summary.mode_regex"
                                        if pattern.pattern.is_regex
                                        else "discord.pattern_ui.summary.mode_word",
                                        language=language,
                                    ),
                                }
                            },
                        ),
                    )
                    for pattern in visible_patterns
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
                        default=not default_reply_as_reply,
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("discord.reply_ui.pattern_add.mode_reply", language=language),
                        value="reply",
                        default=default_reply_as_reply,
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
        default_event_id: int | None = None,
        default_message: str | None = None,
        bound_message: discord.InteractionMessage | None = None,
    ) -> None:
        super().__init__(title=localizer.text("discord.reply_ui.event_add.title", language=language), timeout=300)
        self._services = services
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._bound_message = bound_message
        visible_events = window_with_included_items(
            adapter_events,
            key=lambda event: event.event.event_id,
            included_keys=[default_event_id] if default_event_id is not None else [],
        )
        self.message = discord.ui.TextInput(
            label=localizer.text("discord.reply_ui.event_add.message_label", language=language),
            style=discord.TextStyle.paragraph,
            default=default_message,
            placeholder=localizer.text(
                "discord.reply_ui.event_add.message_placeholder",
                language=language,
                sources={
                    "view": {
                        "example_channel": localizer.text("discord.reply_ui.event_add.example_channel", language=language),
                        "example_state": localizer.text("discord.reply_ui.event_add.example_state", language=language),
                    }
                },
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
                        label=_adapter_event_label(
                            event,
                            localizer=localizer,
                            language=language,
                            scope="discord.reply_ui.event_add",
                        ),
                        value=_encode_adapter_event_target(event.event.event_id),
                        default=event.event.event_id == default_event_id,
                        description=localizer.text(
                            "discord.reply_ui.event_add.trigger_option_description",
                            language=language,
                            sources={
                                "view": {
                                    "login": event.channel.login[:80],
                                    "state": _event_state_label(
                                        event.event.event_key,
                                        localizer=localizer,
                                        language=language,
                                        scope="discord.reply_ui.event_add",
                                    ).lower(),
                                }
                            },
                        ),
                    )
                    for event in visible_events
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
                            sources={
                                "view": {
                                    "pattern": _pattern_label(
                                        reply.pattern,
                                        localizer=localizer,
                                        language=language,
                                        scope="discord.reply_ui.action",
                                    )
                                }
                            },
                        ),
                    )
                    if isinstance(reply, ReplyPresentation)
                    else discord.SelectOption(
                        label=(
                            reply.action.message_template
                            or localizer.text("discord.reply_ui.action.untitled_event_action", language=language)
                        )[:100],
                        value=_encode_adapter_event_target(reply.event.event.event_id),
                        description=localizer.text(
                            "discord.reply_ui.action.linked_event_description",
                            language=language,
                            sources={
                                "view": {
                                    "event": _adapter_event_label(
                                        reply.event,
                                        localizer=localizer,
                                        language=language,
                                        scope="discord.reply_ui.action",
                                    )
                                }
                            },
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
