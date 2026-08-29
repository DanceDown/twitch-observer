from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest

from src.database.connection import AdapterEventActionRecord, AdapterEventRecord, PatternRecord
from src.entrypoints.discord.commands.live_state_commands import register_live_state_commands
from src.entrypoints.discord.commands.write_commands import register_write_commands
from src.entrypoints.discord.ui.live_state_ui import ChannelEventActionModal, ChannelEventModal
from src.entrypoints.discord.ui.patterns.channels_modal import PatternChannelsModal
from src.entrypoints.discord.ui.patterns.selection import PatternPickerView
from src.entrypoints.discord.ui.patterns.state import PatternFormState
from src.entrypoints.discord.ui.patterns.users_modal import PatternUsersModal
from src.entrypoints.discord.ui.reply_ui import PatternReplyAddModal
from src.entrypoints.discord.ui.write_ui import WriteModal
from src.localization import Localizer
from src.services.discord_ui_queries import (
    AdapterEventActionPresentation,
    AdapterEventPresentation,
    PatternPresentation,
    TrackedChannelPresentation,
    TrackedUserPresentation,
    WriteReplyCandidatePresentation,
)


def _tracked_channels(count: int) -> list[TrackedChannelPresentation]:
    return [
        TrackedChannelPresentation(
            user_id=str(index),
            login=f"channel{index}",
            display_name=f"Channel {index}",
            color=None,
        )
        for index in range(count)
    ]


def _tracked_users(count: int) -> list[TrackedUserPresentation]:
    return [
        TrackedUserPresentation(
            user_id=str(index),
            login=f"user{index}",
            display_name=f"User {index}",
        )
        for index in range(count)
    ]


def _reply_candidates(count: int) -> list[WriteReplyCandidatePresentation]:
    now = datetime.now(UTC)
    return [
        WriteReplyCandidatePresentation(
            message_id=f"msg-{index}",
            twitch_channel_id=f"chan-{index}",
            username=f"user{index}",
            content=f"content {index}",
            timestamp=now,
        )
        for index in range(count)
    ]


def _adapter_action(index: int) -> AdapterEventActionPresentation:
    channel = TrackedChannelPresentation(
        user_id=str(index),
        login=f"channel{index}",
        display_name=f"Channel {index}",
        color=None,
    )
    event = AdapterEventPresentation(
        event=AdapterEventRecord(
            event_id=index,
            thread_id=1,
            adapter_key="twitch",
            subject_type="channel",
            subject_id=str(index),
            event_key="stream.online" if index % 2 else "stream.offline",
            disabled=False,
        ),
        channel=channel,
    )
    return AdapterEventActionPresentation(
        event=event,
        action=AdapterEventActionRecord(
            event_id=index,
            action_type="discord_notify",
            message_template=None,
            reply_as_reply=False,
            disabled=False,
            color=None,
        ),
        display_index=index,
    )


@dataclass
class _PatternParent:
    state: PatternFormState

    def text(self, key: str) -> str:
        return key


@dataclass
class _FakeWriteProvider:
    language: str = "german"
    tracked_channels: list[TrackedChannelPresentation] = field(default_factory=list)
    recent_replies: list[WriteReplyCandidatePresentation] = field(default_factory=list)
    selected_reply: WriteReplyCandidatePresentation | None = None

    async def get_thread_language(self, _discord_channel_id: int) -> str:
        return self.language

    async def list_tracked_channels(self, _discord_channel_id: int) -> list[TrackedChannelPresentation]:
        return list(self.tracked_channels)

    async def list_recent_write_reply_candidates(
        self,
        *,
        discord_channel_id: int,
        max_age_minutes: int,
        limit: int,
    ) -> list[WriteReplyCandidatePresentation]:
        _ = (discord_channel_id, max_age_minutes, limit)
        return list(self.recent_replies)

    async def get_write_reply_candidate(
        self,
        *,
        discord_channel_id: int,
        message_id: str,
    ) -> WriteReplyCandidatePresentation | None:
        _ = discord_channel_id
        if self.selected_reply is not None and self.selected_reply.message_id == message_id:
            return self.selected_reply
        return None


@dataclass
class _FakeLiveProvider:
    language: str = "german"
    tracked_channels: list[TrackedChannelPresentation] = field(default_factory=list)
    actions: list[AdapterEventActionPresentation] = field(default_factory=list)

    async def get_thread_language(self, _discord_channel_id: int) -> str:
        return self.language

    async def list_tracked_channels(self, _discord_channel_id: int) -> list[TrackedChannelPresentation]:
        return list(self.tracked_channels)

    async def list_adapter_event_actions(self, _discord_channel_id: int) -> list[AdapterEventActionPresentation]:
        return list(self.actions)


@dataclass
class _FakePatternProvider:
    language: str = "german"
    patterns: list[PatternPresentation] = field(default_factory=list)

    async def get_thread_language(self, _discord_channel_id: int) -> str:
        return self.language

    async def list_patterns(self, _discord_channel_id: int) -> list[PatternPresentation]:
        return list(self.patterns)

    async def get_pattern(self, _discord_channel_id: int, pattern_id: int) -> PatternPresentation | None:
        return next((pattern for pattern in self.patterns if pattern.pattern.pattern_id == pattern_id), None)


@dataclass
class _FakeResponse:
    modal: object | None = None

    async def send_modal(self, modal: object) -> None:
        self.modal = modal


@dataclass
class _FakeDeferredResponse:
    done: bool = False
    defer_ephemeral: bool | None = None

    def is_done(self) -> bool:
        return self.done

    async def defer(self, *, ephemeral: bool = False) -> None:
        self.done = True
        self.defer_ephemeral = ephemeral


@dataclass
class _FakeEditableMessage:
    edited_embed: discord.Embed | None = None
    edited_view: object | None = None

    async def edit(self, *, embed: discord.Embed | None = None, view: object | None = None) -> None:
        self.edited_embed = embed
        self.edited_view = view


@dataclass
class _FakeInteraction:
    channel_id: int = 100
    user: object = field(default_factory=lambda: SimpleNamespace(id=200))
    response: _FakeResponse = field(default_factory=_FakeResponse)


@dataclass
class _FakeDeferredInteraction:
    channel_id: int = 100
    user: object = field(default_factory=lambda: SimpleNamespace(id=200))
    response: _FakeDeferredResponse = field(default_factory=_FakeDeferredResponse)
    original_message: _FakeEditableMessage = field(default_factory=_FakeEditableMessage)

    async def edit_original_response(self, *, embed: discord.Embed, view: object | None = None) -> _FakeEditableMessage:
        self.original_message.edited_embed = embed
        self.original_message.edited_view = view
        return self.original_message


def _pattern_presentation(pattern_id: int) -> PatternPresentation:
    return PatternPresentation(
        display_index=1,
        pattern=PatternRecord(
            thread_id=1,
            pattern_id=pattern_id,
            regex="hello",
            channel_scope_mode="all_tracked",
            channel_scope_ids=(),
            user_scope_mode="all_users",
            user_scope_ids=(),
            sub_state="all",
            offline_state="both",
            is_regex=False,
            case_sensitive=False,
            color=None,
            disabled=False,
            priority=0,
        ),
        channel_logins=(),
        channel_display_names=(),
        user_logins=(),
        user_display_names=(),
    )


def test_write_modal_includes_selected_items_beyond_first_25() -> None:
    localizer = Localizer.from_directory()
    modal = WriteModal(
        services=object(),  # type: ignore[arg-type]
        discord_channel_id=100,
        requester_id=200,
        tracked_channels=_tracked_channels(30),
        reply_candidates=_reply_candidates(30),
        localizer=localizer,
        language="german",
        default_channel_login="channel29",
        default_message="hello",
        default_reply_parent_message_id="msg-29",
    )

    channel_values = [option.value for option in modal.channel.component.options]
    reply_values = [option.value for option in modal.reply_target.component.options]

    assert "channel29" in channel_values
    assert "msg-29" in reply_values
    assert modal.message.default == "hello"
    assert any(option.value == "channel29" and option.default for option in modal.channel.component.options)
    assert any(option.value == "msg-29" and option.default for option in modal.reply_target.component.options)


def test_pattern_scope_modals_include_selected_items_beyond_first_25() -> None:
    parent = _PatternParent(
        state=PatternFormState(
            channel_scope_mode="only_selected",
            selected_channels=["channel29"],
            selected_channel_names=["Channel 29"],
            user_scope_mode="only_selected",
            selected_users=["user29"],
            selected_user_names=["User 29"],
        )
    )

    channel_modal = PatternChannelsModal(parent=parent, tracked_channels=_tracked_channels(30))
    user_modal = PatternUsersModal(parent=parent, tracked_users=_tracked_users(30))

    assert "channel29" in [option.value for option in channel_modal.channels.component.options]
    assert "user29" in [option.value for option in user_modal.users.component.options]


def test_pattern_reply_modal_includes_selected_pattern_beyond_first_25() -> None:
    localizer = Localizer.from_directory()
    patterns = [
        PatternPresentation(
            display_index=index,
            pattern=SimpleNamespace(pattern_id=index, regex=f"pattern {index}", is_regex=False),
            channel_logins=(),
            channel_display_names=(),
            user_logins=(),
            user_display_names=(),
        )
        for index in range(1, 31)
    ]

    modal = PatternReplyAddModal(
        services=object(),  # type: ignore[arg-type]
        discord_channel_id=100,
        requester_id=200,
        patterns=patterns,
        localizer=localizer,
        language="german",
        default_pattern_id=30,
    )

    assert "pattern:30" in [option.value for option in modal.pattern.component.options]


def test_live_state_modals_include_selected_items_beyond_first_25() -> None:
    localizer = Localizer.from_directory()
    tracked_channels = _tracked_channels(30)
    actions = [_adapter_action(index) for index in range(1, 31)]

    add_modal = ChannelEventModal(
        title="add",
        services=object(),  # type: ignore[arg-type]
        discord_channel_id=100,
        requester_id=200,
        tracked_channels=tracked_channels,
        localizer=localizer,
        language="german",
        default_channel_id="channel29",
        default_event_key="stream.online",
    )
    action_modal = ChannelEventActionModal(
        title="remove",
        services=object(),  # type: ignore[arg-type]
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        actions=actions,
        localizer=localizer,
        language="german",
        default_notification_value="29:stream.online",
    )

    assert "29" in [option.value for option in add_modal.channel.component.options]
    assert "29:stream.online" in [option.value for option in action_modal.notification.component.options]


@pytest.mark.asyncio
async def test_pattern_edit_selection_opens_editor_after_deferred_modal_submit() -> None:
    localizer = Localizer.from_directory()
    provider = _FakePatternProvider(patterns=[_pattern_presentation(14)])
    picker = PatternPickerView(
        owner_id=200,
        language="german",
        services=object(),  # type: ignore[arg-type]
        data_provider=provider,  # type: ignore[arg-type]
        discord_channel_id=100,
        localizer=localizer,
    )
    interaction = _FakeDeferredInteraction()

    await picker.submit_selection(interaction, 14)  # type: ignore[arg-type]

    assert interaction.response.defer_ephemeral is True
    editor_view = interaction.original_message.edited_view
    assert editor_view is not None
    assert editor_view.bound_message is interaction.original_message
    assert editor_view.state.pattern_id == 14


@pytest.mark.asyncio
async def test_write_command_prefills_modal_and_includes_selected_reply_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    provider = _FakeWriteProvider(
        tracked_channels=_tracked_channels(30),
        recent_replies=_reply_candidates(25),
        selected_reply=WriteReplyCandidatePresentation(
            message_id="msg-29",
            twitch_channel_id="chan-29",
            username="user29",
            content="content 29",
            timestamp=datetime.now(UTC),
        ),
    )
    captured: dict[str, object] = {}

    async def fake_ensure(*_args, **_kwargs) -> bool:
        return True

    class FakeModal:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("src.entrypoints.discord.commands.write_commands.ensure_ui_flow_allowed", fake_ensure)
    monkeypatch.setattr("src.entrypoints.discord.commands.write_commands.WriteModal", FakeModal)

    register_write_commands(
        tree,
        services=object(),  # type: ignore[arg-type]
        ui_data_provider=provider,  # type: ignore[arg-type]
        localizer=localizer,
        reply_candidate_max_age_minutes=60,
        reply_candidate_limit=25,
    )
    command = next(command for command in tree.get_commands() if command.name == "write")
    interaction = _FakeInteraction()

    await command.callback(
        interaction,
        twitch_channel_login="channel29",
        message=None,
        reply_parent_message_id="msg-29",
    )

    assert interaction.response.modal is not None
    assert captured["default_channel_login"] == "channel29"
    assert captured["default_reply_parent_message_id"] == "msg-29"
    assert any(candidate.message_id == "msg-29" for candidate in captured["reply_candidates"])


@pytest.mark.asyncio
async def test_liveping_add_opens_prefilled_modal_when_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    provider = _FakeLiveProvider(tracked_channels=_tracked_channels(30))
    captured: dict[str, object] = {}

    async def fake_ensure(*_args, **_kwargs) -> bool:
        return True

    class FakeModal:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("src.entrypoints.discord.commands.live_state_commands.ensure_ui_flow_allowed", fake_ensure)
    monkeypatch.setattr("src.entrypoints.discord.commands.live_state_commands.ChannelEventModal", FakeModal)

    register_live_state_commands(
        tree,
        services=object(),  # type: ignore[arg-type]
        ui_data_provider=provider,  # type: ignore[arg-type]
        localizer=localizer,
    )
    liveping_group = next(command for command in tree.get_commands() if command.name == "liveping")
    add_command = next(command for command in liveping_group.commands if command.name == "add")
    interaction = _FakeInteraction()

    await add_command.callback(
        interaction,
        twitch_channel_login="channel29",
        state=None,
    )

    assert interaction.response.modal is not None
    assert captured["default_channel_id"] == "channel29"


@pytest.mark.asyncio
async def test_liveping_add_dispatches_directly_with_stream_event_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(client)
    localizer = Localizer.from_directory()
    provider = _FakeLiveProvider(tracked_channels=_tracked_channels(5))
    captured: dict[str, object] = {}

    async def fake_ensure(*_args, **_kwargs) -> bool:
        return True

    async def fake_dispatch(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ephemeral=True)

    async def fake_send_initial_result(interaction, result) -> None:
        interaction.sent_result = result

    monkeypatch.setattr("src.entrypoints.discord.commands.live_state_commands.ensure_ui_flow_allowed", fake_ensure)
    monkeypatch.setattr("src.entrypoints.discord.commands.live_state_commands.dispatch_add_channel_event", fake_dispatch)
    monkeypatch.setattr("src.entrypoints.discord.commands.live_state_commands.send_initial_result", fake_send_initial_result)

    register_live_state_commands(
        tree,
        services=object(),  # type: ignore[arg-type]
        ui_data_provider=provider,  # type: ignore[arg-type]
        localizer=localizer,
    )
    liveping_group = next(command for command in tree.get_commands() if command.name == "liveping")
    add_command = next(command for command in liveping_group.commands if command.name == "add")
    interaction = _FakeInteraction()

    await add_command.callback(
        interaction,
        twitch_channel_login="channel3",
        state=discord.app_commands.Choice(name="live", value="stream.online"),
    )

    assert captured["twitch_channel_id"] == "3"
    assert captured["event_kind"].value == "stream.online"
