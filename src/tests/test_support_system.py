from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from src.database.records import SupportTicketRecord, ThreadRecord
from src.entrypoints.discord.commands.support_commands import register_support_commands
from src.entrypoints.discord.ui.support_ui import SupportTicketView
from src.events.commands import AnswerSupportTicketCommand, CloseSupportTicketCommand, CreateSupportTicketCommand, ShowSupportTicketCommand
from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.support_command_service import SupportCommandService
from src.utils.discord_embeds import EMBED_COLORS, build_result_embed, resolve_support_ticket_color


@dataclass
class InMemorySupportTicketRepository:
    tickets: dict[int, SupportTicketRecord] = field(default_factory=dict)
    next_ticket_id: int = 1

    async def create_ticket(
        self,
        *,
        source_discord_channel_id: int,
        requester_discord_user_id: int,
        category: str,
        title: str,
        description: str,
        language: str,
    ) -> SupportTicketRecord:
        ticket_id = self.next_ticket_id
        self.next_ticket_id += 1
        now = _now(ticket_id)
        ticket = SupportTicketRecord(
            ticket_id=ticket_id,
            source_discord_channel_id=source_discord_channel_id,
            requester_discord_user_id=requester_discord_user_id,
            category=category,
            title=title,
            description=description,
            status="open",
            language=language,
            support_message_id=None,
            response_subject=None,
            response_body=None,
            responded_by_discord_user_id=None,
            responded_at=None,
            closed_by_discord_user_id=None,
            closed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.tickets[ticket_id] = ticket
        return ticket

    async def set_support_message_id(self, *, ticket_id: int, support_message_id: int) -> SupportTicketRecord | None:
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return None
        updated = replace(ticket, support_message_id=support_message_id, updated_at=_now(ticket_id, seconds=1))
        self.tickets[ticket_id] = updated
        return updated

    async def get_ticket(self, *, ticket_id: int) -> SupportTicketRecord | None:
        return self.tickets.get(ticket_id)

    async def list_open_tickets_with_messages(self) -> list[SupportTicketRecord]:
        return [
            ticket
            for ticket in self.tickets.values()
            if ticket.status == "open" and ticket.support_message_id is not None
        ]

    async def answer_ticket(
        self,
        *,
        ticket_id: int,
        responder_discord_user_id: int,
        response_subject: str,
        response_body: str,
    ) -> SupportTicketRecord | None:
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.status != "open":
            return None
        updated = replace(
            ticket,
            status="answered",
            response_subject=response_subject,
            response_body=response_body,
            responded_by_discord_user_id=responder_discord_user_id,
            responded_at=_now(ticket_id, seconds=2),
            updated_at=_now(ticket_id, seconds=2),
        )
        self.tickets[ticket_id] = updated
        return updated

    async def close_ticket(self, *, ticket_id: int, closer_discord_user_id: int) -> SupportTicketRecord | None:
        ticket = self.tickets.get(ticket_id)
        if ticket is None or ticket.status != "open":
            return None
        updated = replace(
            ticket,
            status="closed",
            closed_by_discord_user_id=closer_discord_user_id,
            closed_at=_now(ticket_id, seconds=3),
            updated_at=_now(ticket_id, seconds=3),
        )
        self.tickets[ticket_id] = updated
        return updated


@dataclass
class InMemoryThreadRepository:
    threads_by_channel: dict[int, ThreadRecord] = field(default_factory=dict)

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel.get(discord_channel_id)

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        for thread in self.threads_by_channel.values():
            if thread.thread_id == thread_id:
                return thread
        return None


class EmptyChannelRepository:
    async def list_channels_for_thread(self, _thread_id: int) -> list:
        return []


class EmptyPatternRepository:
    async def list_patterns_for_thread(self, _thread_id: int, *, is_regex: bool | None = None) -> list:
        _ = is_regex
        return []


class EmptyReplyRepository:
    async def list_replies_for_thread(self, _thread_id: int, *, include_disabled: bool = True) -> list:
        _ = include_disabled
        return []


@dataclass
class FakeDiscordResponse:
    done: bool = False

    def is_done(self) -> bool:
        return self.done

    async def defer(self, *, ephemeral: bool = False) -> None:
        _ = ephemeral
        self.done = True

    async def send_message(self, *, embed: discord.Embed, ephemeral: bool, view: object | None = None) -> None:
        _ = (embed, ephemeral, view)
        self.done = True


@dataclass
class FakeDiscordChannel:
    channel_id: int
    sent: list[dict[str, object]] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.channel_id

    async def send(self, **kwargs) -> object:
        self.sent.append(kwargs)
        return SimpleNamespace(id=9000 + len(self.sent))


@dataclass
class FakeDiscordClient:
    channels: dict[int, FakeDiscordChannel]

    def get_channel(self, channel_id: int) -> FakeDiscordChannel | None:
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> FakeDiscordChannel | None:
        return self.channels.get(channel_id)


@dataclass
class FakeInteraction:
    client: FakeDiscordClient
    channel_id: int
    user_id: int
    locale: str = "de-DE"
    response: FakeDiscordResponse = field(default_factory=FakeDiscordResponse)
    edited_original_embed: discord.Embed | None = None
    message: object | None = None

    @property
    def user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def edit_original_response(self, *, embed: discord.Embed) -> None:
        self.edited_original_embed = embed

    async def original_response(self) -> object:
        return SimpleNamespace(id=777)


@dataclass
class FakeSupportMessage:
    edited_embed: discord.Embed | None = None
    edited_view: object | None = None

    async def edit(self, *, embed: discord.Embed, view: object | None = None) -> None:
        self.edited_embed = embed
        self.edited_view = view


@pytest.mark.asyncio
async def test_support_without_config_returns_ephemeral_unavailable() -> None:
    service = _service(support_channel_id=None, thread_language="german")

    result = await service.handle_create(
        CreateSupportTicketCommand(
            discord_channel_id=100,
            requester_id=200,
            category="bug",
            title="Ping kaputt",
            description="Bitte anschauen",
            language_hint="german",
        )
    )

    assert result.ticket is None
    assert result.result.ephemeral is True
    assert result.result.style is DiscordResultStyle.ERROR
    assert result.result.message == "Support ist derzeit nicht verfügbar."


@pytest.mark.asyncio
async def test_support_command_creates_ticket_and_sends_colored_support_embed() -> None:
    localizer = Localizer.from_directory()
    support_channel = FakeDiscordChannel(channel_id=500)
    client = FakeDiscordClient(channels={500: support_channel})
    service = _service(support_channel_id=500, localizer=localizer)
    services = SimpleNamespace(support=service)
    tree_client = discord.Client(intents=discord.Intents.default())
    tree = discord.app_commands.CommandTree(tree_client)

    register_support_commands(tree, services, object(), localizer)
    support_command = next(command for command in tree.get_commands() if command.name == "support")
    interaction = FakeInteraction(client=client, channel_id=100, user_id=200)

    await support_command.callback(
        interaction,
        category=discord.app_commands.Choice(name="Bug", value="bug"),
        title="Ping 14",
        description="Kommt nicht durch",
    )

    assert len(support_channel.sent) == 1
    sent_embed = support_channel.sent[0]["embed"]
    sent_view = support_channel.sent[0]["view"]
    assert isinstance(sent_embed, discord.Embed)
    assert isinstance(sent_view, SupportTicketView)
    assert sent_embed.color.value == resolve_support_ticket_color(category="bug")
    assert sent_embed.title == "Bug: Ping 14"
    assert sent_embed.footer.text is not None
    assert sent_embed.footer.text.startswith("Ticket #1")
    assert interaction.edited_original_embed is not None
    assert interaction.edited_original_embed.description is not None
    assert "Ticket #1" in interaction.edited_original_embed.description
    assert service.support_ticket_repository.tickets[1].support_message_id == 9001


@pytest.mark.asyncio
async def test_support_answer_uses_thread_color_markdown_and_original_request() -> None:
    repository = InMemorySupportTicketRepository()
    service = _service(repository=repository, thread_color="#123456")
    created = await _create_ticket(service)

    prepared = await service.prepare_answer(
        AnswerSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            responder_id=300,
            subject="How to Ping",
            body="# Überschrift\nNutze `/ping add ...` @everyone",
        )
    )

    assert prepared.ticket is not None
    embed = build_result_embed(prepared.result)
    assert embed.color.value == 0x123456
    assert embed.description is not None
    assert embed.description.startswith("# Überschrift")
    assert "@everyone" in embed.description
    assert "Ping 14" in embed.description
    assert "Kommt nicht durch" in embed.description

    updated = await service.mark_answered(
        AnswerSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            responder_id=300,
            subject="How to Ping",
            body="# Überschrift\nNutze `/ping add ...` @everyone",
        )
    )

    assert updated.ticket is not None
    assert updated.ticket.status == "answered"


@pytest.mark.asyncio
async def test_support_close_uses_error_color_and_marks_closed() -> None:
    service = _service()
    created = await _create_ticket(service)

    prepared = await service.prepare_close(
        CloseSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            closer_id=300,
        )
    )

    assert prepared.ticket is not None
    embed = build_result_embed(prepared.result)
    assert embed.color.value == EMBED_COLORS[DiscordResultStyle.ERROR]

    updated = await service.mark_closed(
        CloseSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            closer_id=300,
        )
    )

    assert updated.ticket is not None
    assert updated.ticket.status == "closed"


@pytest.mark.asyncio
async def test_support_ticket_cannot_be_handled_twice() -> None:
    service = _service()
    created = await _create_ticket(service)
    first_update = await service.mark_answered(
        AnswerSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            responder_id=300,
            subject="Done",
            body="Answered",
        )
    )

    second_prepare = await service.prepare_close(
        CloseSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            closer_id=300,
        )
    )

    assert first_update.ticket is not None
    assert first_update.ticket.status == "answered"
    assert second_prepare.ticket is None
    assert second_prepare.result.style is DiscordResultStyle.ERROR


@pytest.mark.asyncio
async def test_support_show_bypasses_thread_user_permission_for_all_sections() -> None:
    service = _service(thread_owner_id=1000)
    created = await _create_ticket(service)

    result = await service.handle_show(
        ShowSupportTicketCommand(
            ticket_id=created.ticket.ticket_id,
            requester_id=2000,
            sections=("channels", "stream_pings", "pings", "auto_replies", "users", "permissions", "account"),
        )
    )

    assert result.style is DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert "Twitch channels" in result.message
    assert "Permissions" in result.message


@pytest.mark.asyncio
async def test_support_close_button_sends_user_notice_and_removes_buttons() -> None:
    localizer = Localizer.from_directory()
    origin_channel = FakeDiscordChannel(channel_id=100)
    service = _service(support_channel_id=500, localizer=localizer)
    created = await _create_ticket(service)
    await service.record_support_message(ticket_id=created.ticket.ticket_id, support_message_id=700)
    support_message = FakeSupportMessage()
    interaction = FakeInteraction(
        client=FakeDiscordClient(channels={100: origin_channel}),
        channel_id=500,
        user_id=300,
        message=support_message,
    )
    view = SupportTicketView(
        ticket_id=created.ticket.ticket_id,
        services=SimpleNamespace(support=service),
        localizer=localizer,
        language="english",
    )
    close_button = next(child for child in view.children if isinstance(child, discord.ui.Button) and child.custom_id == "support:close:1")

    await close_button.callback(interaction)

    assert len(origin_channel.sent) == 1
    assert support_message.edited_view is None
    assert support_message.edited_embed is not None
    assert "Closed" in (support_message.edited_embed.description or "")
    assert service.support_ticket_repository.tickets[1].status == "closed"


async def _create_ticket(service: SupportCommandService):
    result = await service.handle_create(
        CreateSupportTicketCommand(
            discord_channel_id=100,
            requester_id=200,
            category="question",
            title="Ping 14",
            description="Kommt nicht durch",
            language_hint="english",
        )
    )
    assert result.ticket is not None
    return result


def _service(
    *,
    support_channel_id: int | None = 500,
    localizer: Localizer | None = None,
    repository: InMemorySupportTicketRepository | None = None,
    thread_color: str | None = None,
    thread_owner_id: int = 200,
    thread_language: str = "english",
) -> SupportCommandService:
    resolved_localizer = localizer or Localizer.from_directory()
    thread = ThreadRecord(
        thread_id=1,
        owner_id=thread_owner_id,
        discord_channel_id=100,
        enabled=True,
        color=thread_color,
        language=thread_language,
    )
    return SupportCommandService(
        support_ticket_repository=repository or InMemorySupportTicketRepository(),
        thread_repository=InMemoryThreadRepository(threads_by_channel={100: thread}),
        channel_repository=EmptyChannelRepository(),
        pattern_repository=EmptyPatternRepository(),
        reply_repository=EmptyReplyRepository(),
        twitch_api=object(),
        support_discord_channel_id=support_channel_id,
        localizer=resolved_localizer,
    )


def _now(ticket_id: int, *, seconds: int = 0) -> datetime:
    return datetime(2026, 8, 29, 12, 0, tzinfo=UTC) + timedelta(minutes=ticket_id, seconds=seconds)
