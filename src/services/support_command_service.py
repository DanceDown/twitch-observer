"""Business logic for Discord support tickets."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

import psycopg

from src.database.connection import (
    AdapterEventActionRepository,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    SupportTicketCreate,
    SupportTicketRecord,
    SupportTicketRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.discord_results import build_result, build_thread_result
from src.errors import DatabasePoolExhaustedError
from src.events.commands import (
    AnswerSupportTicketCommand,
    CloseSupportTicketCommand,
    CreateSupportTicketCommand,
    ShowSupportTicketCommand,
)
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.services.patterns.show_renderer import ShowSectionRenderer
from src.services.twitch_gateways import TwitchDirectoryGateway

logger = logging.getLogger(__name__)

SUPPORT_TICKET_CATEGORIES = ("bug", "question", "idea", "other")
SUPPORT_TICKET_OPEN = "open"
SUPPORT_TITLE_MAX_LENGTH = 120
SUPPORT_DESCRIPTION_MAX_LENGTH = 1500
SUPPORT_RESPONSE_SUBJECT_MAX_LENGTH = 120
SUPPORT_RESPONSE_BODY_MAX_LENGTH = 1500
_SHOW_SECTIONS = ("channels", "stream_pings", "pings", "auto_replies", "users", "permissions", "account")

ShowSectionRendererFn = Callable[[ThreadRecord], Awaitable[str]]


@dataclass(slots=True, frozen=True)
class SupportTicketCreateResult:
    """Outcome of creating a support ticket."""

    result: DiscordCommandResult
    ticket: SupportTicketRecord | None
    support_discord_channel_id: int | None


@dataclass(slots=True, frozen=True)
class SupportTicketMessageResult:
    """Prepared user-facing support ticket message or an error result."""

    result: DiscordCommandResult
    ticket: SupportTicketRecord | None


@dataclass(slots=True, frozen=True)
class SupportTicketUpdateResult:
    """Outcome of changing a ticket status."""

    result: DiscordCommandResult
    ticket: SupportTicketRecord | None


@dataclass(slots=True, frozen=True)
class _TicketResultOptions:
    """Display switches for support-ticket command results."""

    style: DiscordResultStyle = DiscordResultStyle.ERROR
    ephemeral: bool = True
    color: str | None = None
    extra_view: dict[str, object] | None = None


_DEFAULT_TICKET_RESULT_OPTIONS = _TicketResultOptions()


@dataclass(slots=True)
class SupportCommandService:
    """Create, answer, close and inspect support tickets."""

    support_ticket_repository: SupportTicketRepository
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    twitch_api: TwitchDirectoryGateway
    support_discord_channel_id: int | None
    tracked_user_repository: TrackedUserRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
    permission_repository: UserPermissionRepository | None = None
    account_repository: TwitchAccountRepository | None = None
    device_flow_repository: TwitchDeviceFlowRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    _renderer: ShowSectionRenderer = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build the shared renderer used by `/support show` actions."""
        self._renderer = ShowSectionRenderer(
            channel_repository=self.channel_repository,
            pattern_repository=self.pattern_repository,
            reply_repository=self.reply_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            adapter_event_action_repository=self.adapter_event_action_repository,
            localizer=self.localizer,
            permission_repository=self.permission_repository,
            account_repository=self.account_repository,
            device_flow_repository=self.device_flow_repository,
        )

    async def handle_create(self, command: CreateSupportTicketCommand) -> SupportTicketCreateResult:
        """Create and persist one new support ticket."""
        language = self.localizer.resolve_language(command.language_hint)
        try:
            language = await self._language_for_source(command.discord_channel_id, command.language_hint)
            return await self._create(command, language=language)
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while creating support ticket.")
            return self._create_error_result(
                "results.support.unexpected_error",
                language=language,
                sources={"view": {"detail": str(error)}},
            )
        except Exception as error:
            logger.exception("Unexpected error while creating support ticket.")
            return self._create_error_result(
                "results.support.unexpected_error",
                language=language,
                sources={"view": {"detail": str(error)}},
            )

    async def _create(self, command: CreateSupportTicketCommand, *, language: str) -> SupportTicketCreateResult:
        if self.support_discord_channel_id is None:
            return self._create_error_result("results.support.unavailable", language=language)

        category = command.category.strip().lower()
        if category not in SUPPORT_TICKET_CATEGORIES:
            return self._create_validation_error(language, "category_invalid")

        title, title_error = self._normalize_required_text(
            command.title,
            max_length=SUPPORT_TITLE_MAX_LENGTH,
            required_detail="title_required",
            too_long_detail="title_too_long",
            language=language,
        )
        if title_error is not None:
            return title_error

        description, description_error = self._normalize_required_text(
            command.description,
            max_length=SUPPORT_DESCRIPTION_MAX_LENGTH,
            required_detail="description_required",
            too_long_detail="description_too_long",
            language=language,
        )
        if description_error is not None:
            return description_error

        ticket = await self.support_ticket_repository.create_ticket(
            SupportTicketCreate(
                source_discord_channel_id=command.discord_channel_id,
                requester_discord_user_id=command.requester_id,
                category=category,
                title=title,
                description=description,
                language=language,
            )
        )
        return SupportTicketCreateResult(
            result=self._ticket_result(
                "results.support.created",
                ticket,
                options=_TicketResultOptions(style=DiscordResultStyle.SUCCESS),
            ),
            ticket=ticket,
            support_discord_channel_id=self.support_discord_channel_id,
        )

    async def record_support_message(self, *, ticket_id: int, support_message_id: int) -> SupportTicketRecord | None:
        """Attach the Discord support-channel message ID to one ticket."""
        try:
            return await self.support_ticket_repository.set_support_message_id(
                ticket_id=ticket_id,
                support_message_id=support_message_id,
            )
        except (DatabasePoolExhaustedError, psycopg.Error):
            logger.warning("Could not record support message ID for ticket_id=%s.", ticket_id, exc_info=True)
            return None

    async def list_open_tickets_with_messages(self) -> list[SupportTicketRecord]:
        """Return open tickets whose persistent views can be restored after a restart."""
        try:
            return await self.support_ticket_repository.list_open_tickets_with_messages()
        except (DatabasePoolExhaustedError, psycopg.Error):
            logger.warning("Could not restore persistent support ticket views.", exc_info=True)
            return []

    async def get_open_ticket_result(
        self,
        *,
        ticket_id: int,
        language_hint: str | None = None,
    ) -> SupportTicketUpdateResult:
        """Load one open ticket for a support-channel action."""
        try:
            ticket = await self.support_ticket_repository.get_ticket(ticket_id=ticket_id)
            if ticket is None:
                return SupportTicketUpdateResult(
                    result=self._plain_result("results.support.ticket_not_found", language=language_hint),
                    ticket=None,
                )
            if ticket.status != SUPPORT_TICKET_OPEN:
                return SupportTicketUpdateResult(
                    result=self._ticket_result("results.support.ticket_not_open", ticket),
                    ticket=None,
                )
            return SupportTicketUpdateResult(
                result=self._ticket_result("results.support.action_ready", ticket),
                ticket=ticket,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while loading support ticket.")
            return SupportTicketUpdateResult(
                result=self._plain_result(
                    "results.support.unexpected_error",
                    language=language_hint,
                    sources={"view": {"detail": str(error)}},
                ),
                ticket=None,
            )
        except Exception as error:
            logger.exception("Unexpected error while loading support ticket.")
            return SupportTicketUpdateResult(
                result=self._plain_result(
                    "results.support.unexpected_error",
                    language=language_hint,
                    sources={"view": {"detail": str(error)}},
                ),
                ticket=None,
            )

    async def prepare_answer(self, command: AnswerSupportTicketCommand) -> SupportTicketMessageResult:
        """Build the user-facing answer result without changing ticket state yet."""
        try:
            ticket_result = await self.get_open_ticket_result(ticket_id=command.ticket_id)
            if ticket_result.ticket is None:
                return SupportTicketMessageResult(result=ticket_result.result, ticket=None)

            subject, subject_error = self._normalize_required_text(
                command.subject,
                max_length=SUPPORT_RESPONSE_SUBJECT_MAX_LENGTH,
                required_detail="subject_required",
                too_long_detail="subject_too_long",
                language=ticket_result.ticket.language,
            )
            if subject_error is not None:
                return SupportTicketMessageResult(result=subject_error.result, ticket=None)

            body, body_error = self._normalize_required_text(
                command.body,
                max_length=SUPPORT_RESPONSE_BODY_MAX_LENGTH,
                required_detail="body_required",
                too_long_detail="body_too_long",
                language=ticket_result.ticket.language,
            )
            if body_error is not None:
                return SupportTicketMessageResult(result=body_error.result, ticket=None)

            thread = await self.thread_repository.get_by_discord_channel_id(ticket_result.ticket.source_discord_channel_id)
            return SupportTicketMessageResult(
                result=self._ticket_result(
                    "results.support.user_answer",
                    ticket_result.ticket,
                    options=_TicketResultOptions(
                        style=DiscordResultStyle.SUCCESS,
                        ephemeral=False,
                        color=thread.color if thread is not None else None,
                        extra_view={"response_subject": subject, "response_body": body},
                    ),
                ),
                ticket=ticket_result.ticket,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while preparing support ticket answer.")
            return SupportTicketMessageResult(
                result=self._plain_result(
                    "results.support.unexpected_error",
                    sources={"view": {"detail": str(error)}},
                ),
                ticket=None,
            )
        except Exception as error:
            logger.exception("Unexpected error while preparing support ticket answer.")
            return SupportTicketMessageResult(
                result=self._plain_result(
                    "results.support.unexpected_error",
                    sources={"view": {"detail": str(error)}},
                ),
                ticket=None,
            )

    async def mark_answered(self, command: AnswerSupportTicketCommand) -> SupportTicketUpdateResult:
        """Persist the answer details after the user-facing delivery succeeded."""
        try:
            subject = command.subject.strip()
            body = command.body.strip()
            updated = await self.support_ticket_repository.answer_ticket(
                ticket_id=command.ticket_id,
                responder_discord_user_id=command.responder_id,
                response_subject=subject,
                response_body=body,
            )
            if updated is None:
                ticket = await self.support_ticket_repository.get_ticket(ticket_id=command.ticket_id)
                language = ticket.language if ticket is not None else None
                return SupportTicketUpdateResult(
                    result=self._plain_result("results.support.ticket_not_open", language=language),
                    ticket=None,
                )
            return SupportTicketUpdateResult(
                result=self._ticket_result(
                    "results.support.answer_recorded",
                    updated,
                    options=_TicketResultOptions(style=DiscordResultStyle.SUCCESS),
                ),
                ticket=updated,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while marking support ticket answered.")
            return SupportTicketUpdateResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )
        except Exception as error:
            logger.exception("Unexpected error while marking support ticket answered.")
            return SupportTicketUpdateResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )

    async def prepare_close(self, command: CloseSupportTicketCommand) -> SupportTicketMessageResult:
        """Build the user-facing close result without changing ticket state yet."""
        try:
            ticket_result = await self.get_open_ticket_result(ticket_id=command.ticket_id)
            if ticket_result.ticket is None:
                return SupportTicketMessageResult(result=ticket_result.result, ticket=None)
            return SupportTicketMessageResult(
                result=self._ticket_result(
                    "results.support.user_closed",
                    ticket_result.ticket,
                    options=_TicketResultOptions(ephemeral=False),
                ),
                ticket=ticket_result.ticket,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while preparing support ticket close.")
            return SupportTicketMessageResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )
        except Exception as error:
            logger.exception("Unexpected error while preparing support ticket close.")
            return SupportTicketMessageResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )

    async def mark_closed(self, command: CloseSupportTicketCommand) -> SupportTicketUpdateResult:
        """Persist a close action after the user-facing delivery succeeded."""
        try:
            updated = await self.support_ticket_repository.close_ticket(
                ticket_id=command.ticket_id,
                closer_discord_user_id=command.closer_id,
            )
            if updated is None:
                ticket = await self.support_ticket_repository.get_ticket(ticket_id=command.ticket_id)
                language = ticket.language if ticket is not None else None
                return SupportTicketUpdateResult(
                    result=self._plain_result("results.support.ticket_not_open", language=language),
                    ticket=None,
                )
            return SupportTicketUpdateResult(
                result=self._ticket_result(
                    "results.support.close_recorded",
                    updated,
                    options=_TicketResultOptions(style=DiscordResultStyle.SUCCESS),
                ),
                ticket=updated,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while marking support ticket closed.")
            return SupportTicketUpdateResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )
        except Exception as error:
            logger.exception("Unexpected error while marking support ticket closed.")
            return SupportTicketUpdateResult(
                result=self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}}),
                ticket=None,
            )

    async def handle_show(self, command: ShowSupportTicketCommand) -> DiscordCommandResult:
        """Render the origin-channel configuration for one support ticket."""
        try:
            ticket = await self.support_ticket_repository.get_ticket(ticket_id=command.ticket_id)
            if ticket is None:
                return self._plain_result("results.support.ticket_not_found")
            thread = await self.thread_repository.get_by_discord_channel_id(ticket.source_discord_channel_id)
            if thread is None:
                return self._ticket_result("results.support.show_not_joined", ticket)

            self._renderer.reset_resolution_cache()
            sections = self._normalize_show_sections(command.sections)
            lines, thumbnail_url = await self._render_show_sections(thread, sections)
            return build_thread_result(
                self.localizer,
                "results.support.show_overview",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                sources={"view": {"sections": [section for section in lines if section]}},
                thumbnail_url=thumbnail_url,
            )
        except DatabasePoolExhaustedError as error:
            logger.exception("Database pool exhausted while rendering support show.")
            return self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}})
        except Exception as error:
            logger.exception("Unexpected error while rendering support show.")
            return self._plain_result("results.support.unexpected_error", sources={"view": {"detail": str(error)}})

    def is_support_channel(self, discord_channel_id: int | None) -> bool:
        """Return whether one interaction came from the configured support channel."""
        return self.support_discord_channel_id is not None and discord_channel_id == self.support_discord_channel_id

    def wrong_channel_result(self, *, language_hint: str | None = None) -> DiscordCommandResult:
        """Build the shared error for support actions outside the configured support channel."""
        return self._plain_result("results.support.wrong_channel", language=language_hint)

    def delivery_failed_result(self, ticket: SupportTicketRecord) -> DiscordCommandResult:
        """Build the shared error for failed origin-channel delivery."""
        return self._ticket_result("results.support.delivery_failed", ticket)

    def support_channel_delivery_failed_result(self, ticket: SupportTicketRecord) -> DiscordCommandResult:
        """Build the shared error for failed support-channel delivery."""
        return self._ticket_result("results.support.support_channel_delivery_failed", ticket)

    async def _language_for_source(self, discord_channel_id: int, language_hint: str | None) -> str:
        thread = await self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is not None:
            return self.localizer.language_for_thread(thread)
        return self.localizer.resolve_language(language_hint)

    def _create_error_result(
        self,
        key: str,
        *,
        language: str | None,
        sources: dict[str, object] | None = None,
    ) -> SupportTicketCreateResult:
        return SupportTicketCreateResult(
            result=self._plain_result(key, language=language, sources=sources),
            ticket=None,
            support_discord_channel_id=self.support_discord_channel_id,
        )

    def _create_validation_error(
        self,
        language: str,
        detail_key: str,
        *,
        sources: dict[str, object] | None = None,
    ) -> SupportTicketCreateResult:
        return self._create_error_result(
            "results.support.validation_error",
            language=language,
            sources={
                "view": {
                    "detail": self.localizer.text(
                        f"results.support.validation.{detail_key}",
                        language=language,
                        sources=sources,
                    )
                }
            },
        )

    def _normalize_required_text(
        self,
        value: str,
        *,
        max_length: int,
        required_detail: str,
        too_long_detail: str,
        language: str,
    ) -> tuple[str, SupportTicketCreateResult | None]:
        normalized = value.strip()
        if not normalized:
            return "", self._create_validation_error(language, required_detail)
        if len(normalized) > max_length:
            return "", self._create_validation_error(language, too_long_detail, sources={"view": {"max_length": max_length}})
        return normalized, None

    def _ticket_result(
        self,
        key: str,
        ticket: SupportTicketRecord,
        *,
        options: _TicketResultOptions = _DEFAULT_TICKET_RESULT_OPTIONS,
    ) -> DiscordCommandResult:
        view = self._ticket_view(ticket)
        if options.extra_view is not None:
            view.update(options.extra_view)
        return build_result(
            self.localizer,
            key,
            language=ticket.language,
            style=options.style,
            ephemeral=options.ephemeral,
            color=options.color,
            sources={"view": view},
        )

    def _plain_result(
        self,
        key: str,
        *,
        language: str | None = None,
        sources: dict[str, object] | None = None,
        style: DiscordResultStyle = DiscordResultStyle.ERROR,
    ) -> DiscordCommandResult:
        return build_result(
            self.localizer,
            key,
            language=language,
            style=style,
            ephemeral=True,
            sources=sources,
        )

    def _ticket_view(self, ticket: SupportTicketRecord) -> dict[str, object]:
        category_label = self.localizer.lookup("discord.support.category", ticket.category, language=ticket.language)
        status_label = self.localizer.lookup("discord.support.status", ticket.status, language=ticket.language)
        return {
            "ticket_id": ticket.ticket_id,
            "source_channel_id": ticket.source_discord_channel_id,
            "requester_id": ticket.requester_discord_user_id,
            "category": ticket.category,
            "category_label": category_label,
            "title": ticket.title,
            "description": ticket.description,
            "status": ticket.status,
            "status_label": status_label,
            "support_message_id": ticket.support_message_id or "",
            "response_subject": ticket.response_subject or "",
            "response_body": ticket.response_body or "",
            "responded_by": ticket.responded_by_discord_user_id or "",
            "responded_at": ticket.responded_at,
            "closed_by": ticket.closed_by_discord_user_id or "",
            "closed_at": ticket.closed_at,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
        }

    @staticmethod
    def _normalize_show_sections(raw_sections: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(section for section in raw_sections if section in _SHOW_SECTIONS)
        return normalized or ("channels",)

    def _show_section_renderers(self) -> Mapping[str, ShowSectionRendererFn]:
        return {
            "channels": self._renderer.render_channels_section,
            "stream_pings": self._renderer.render_channel_events_section,
            "pings": self._renderer.render_patterns_section,
            "auto_replies": self._renderer.render_auto_replies_section,
            "users": self._renderer.render_users_section,
            "permissions": self._renderer.render_permissions_section,
        }

    async def _render_show_sections(self, thread: ThreadRecord, sections: tuple[str, ...]) -> tuple[list[str], str | None]:
        lines: list[str] = []
        thumbnail_url = None
        section_renderers = self._show_section_renderers()
        for section in sections:
            if section == "account":
                account_section, thumbnail_url = await self._renderer.render_account_section(thread)
                lines.append(account_section)
                continue
            renderer = section_renderers.get(section)
            if renderer is not None:
                lines.append(await renderer(thread))
        return [line for line in lines if line], thumbnail_url
