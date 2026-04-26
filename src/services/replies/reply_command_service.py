"""Business logic for managing auto-reply configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.adapters.twitch_api import TwitchAPIClient
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordReplyRequestedEvent,
    DiscordResultStyle,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.discord_embeds import escape_discord_preserving_links
from src.utils.permissions import ObserverPermission


@dataclass(slots=True)
class ReplyCommandService:
    """Handle `/reply` add/remove/disable/enable requests."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    channel_repository: ChannelRepository | None = None
    twitch_api: TwitchAPIClient | None = None
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_REPLY_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordReplyRequestedEvent) -> None:
        try:
            result = await self._handle_action(event)
        except ValueError as error:
            result = self._event_result(
                event,
                "results.validation_error",
                DETAIL=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(
        self,
        event: DiscordReplyRequestedEvent,
    ) -> DiscordCommandResult:
        if event.action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_REPLIES
            denial_key = "results.reply.manage_permission_denied"
        else:
            required_permission = ObserverPermission.TOGGLE_REPLIES
            denial_key = "results.reply.toggle_permission_denied"

        thread = self._ensure_thread_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=required_permission,
            denial_key=denial_key,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        if event.target_type == "adapter_event":
            return await self._handle_adapter_event_action(thread, event)

        pattern = self.pattern_repository.get_pattern_by_id(
            thread_id=thread.thread_id,
            p_index=event.pattern_id,
        )
        if pattern is None:
            return self.localizer.thread_result(
                "results.reply.pattern_not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "add":
            linked_account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if linked_account is None:
                return self.localizer.thread_result(
                    "results.reply.no_linked_account",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            message = (event.message or "").strip()
            if not message:
                raise ValueError(self.localizer.text("results.reply.empty_message", language=thread.language))
            if len(message) > 500:
                raise ValueError(self.localizer.text("results.reply.message_too_long", language=thread.language))
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is not None:
                return self.localizer.thread_result(
                    "results.reply.already_exists",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            created = self.reply_repository.add_reply(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                reply_message=message,
                reply_as_reply=event.reply_as_reply,
            )
            assert created is not None
            return self.localizer.thread_result(
                "results.reply.added_pattern",
                thread=thread,
                ID=pattern.p_index,
                MODE=self.localizer.text(
                    "results.reply.mode.reply" if created.reply_as_reply else "results.reply.mode.message",
                    language=thread.language,
                ),
                MESSAGE=escape_discord_preserving_links(created.reply_message),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "remove":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return self.localizer.thread_result(
                    "results.reply.none_configured",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            cleared = self.reply_repository.remove_reply(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            assert cleared is not None
            return self.localizer.thread_result(
                "results.reply.removed_pattern",
                thread=thread,
                ID=pattern.p_index,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "disable":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return self.localizer.thread_result(
                    "results.reply.none_configured",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if existing_reply.disabled:
                return self.localizer.thread_result(
                    "results.reply.already_disabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=True,
            )
            assert disabled_reply is not None
            return self.localizer.thread_result(
                "results.reply.disabled_pattern",
                thread=thread,
                ID=pattern.p_index,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "enable":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return self.localizer.thread_result(
                    "results.reply.none_configured",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if not existing_reply.disabled:
                return self.localizer.thread_result(
                    "results.reply.already_enabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=False,
            )
            assert enabled_reply is not None
            return self.localizer.thread_result(
                "results.reply.enabled_pattern",
                thread=thread,
                ID=pattern.p_index,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError(self.localizer.text("results.reply.unsupported_action", language=thread.language))

    async def _handle_adapter_event_action(
        self,
        thread: ThreadRecord,
        event: DiscordReplyRequestedEvent,
    ) -> DiscordCommandResult:
        if self.adapter_event_repository is None or self.adapter_event_action_repository is None:
            raise ValueError(self.localizer.text("results.reply.event_unavailable", language=thread.language))
        if event.adapter_event_id is None:
            raise ValueError(self.localizer.text("results.reply.missing_event", language=thread.language))

        adapter_event = next(
            (
                item
                for item in self.adapter_event_repository.list_events_for_thread(
                    thread.thread_id,
                    include_disabled=True,
                )
                if item.event_id == event.adapter_event_id
            ),
            None,
        )
        if adapter_event is None:
            return self.localizer.thread_result(
                "results.reply.event_not_found",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        state_label = STREAM_EVENT_KEY_TO_STATE.get(adapter_event.event_key)
        if adapter_event.adapter_key != TWITCH_ADAPTER_KEY or adapter_event.subject_type != CHANNEL_SUBJECT_TYPE or state_label is None:
            raise ValueError(self.localizer.text("results.reply.unsupported_event", language=thread.language))

        channel_name = adapter_event.subject_id
        if self.twitch_api is not None:
            try:
                twitch_channel = await self.twitch_api.get_user_by_id(
                    adapter_event.subject_id,
                )
                channel_name = twitch_channel.display_name
            except Exception:
                pass

        existing_reply = self.adapter_event_action_repository.get_action(
            event_id=adapter_event.event_id,
            action_type=TWITCH_SEND_MESSAGE_ACTION,
        )

        if event.action == "add":
            linked_account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if linked_account is None:
                return self.localizer.thread_result(
                    "results.reply.no_linked_account",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            message = (event.message or "").strip()
            if not message:
                raise ValueError(self.localizer.text("results.reply.empty_message", language=thread.language))
            if len(message) > 500:
                raise ValueError(self.localizer.text("results.reply.message_too_long", language=thread.language))
            created = self.adapter_event_action_repository.upsert_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                message_template=message,
                reply_as_reply=False,
            )
            return self.localizer.thread_result(
                "results.reply.added_event",
                thread=thread,
                CHANNEL=channel_name,
                STATE=state_label,
                MESSAGE=escape_discord_preserving_links(created.message_template or ""),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if existing_reply is None:
            return self.localizer.thread_result(
                "results.reply.none_configured_event",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        if event.action == "remove":
            removed = self.adapter_event_action_repository.remove_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
            )
            assert removed is not None
            return self.localizer.thread_result(
                "results.reply.removed_event",
                thread=thread,
                CHANNEL=channel_name,
                STATE=state_label,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "disable":
            if existing_reply.disabled:
                return self.localizer.thread_result(
                    "results.reply.already_disabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=True,
            )
            assert disabled_reply is not None
            return self.localizer.thread_result(
                "results.reply.disabled_event",
                thread=thread,
                CHANNEL=channel_name,
                STATE=state_label,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "enable":
            if not existing_reply.disabled:
                return self.localizer.thread_result(
                    "results.reply.already_enabled",
                    thread=thread,
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=False,
            )
            assert enabled_reply is not None
            return self.localizer.thread_result(
                "results.reply.enabled_event",
                thread=thread,
                CHANNEL=channel_name,
                STATE=state_label,
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError(self.localizer.text("results.reply.unsupported_action", language=thread.language))

    def _ensure_thread_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_key: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return self.localizer.result(
                "results.not_joined",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return self.localizer.thread_result(
                denial_key,
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    def _event_result(
        self,
        event: DiscordReplyRequestedEvent,
        key: str,
        *,
        style: DiscordResultStyle,
        ephemeral: bool,
        **placeholders: object,
    ) -> DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        return self.localizer.thread_result(key, thread=thread, style=style, ephemeral=ephemeral, **placeholders)

