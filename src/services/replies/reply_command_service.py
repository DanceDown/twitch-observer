from __future__ import annotations

"""Business logic for managing auto-reply configuration."""

from dataclasses import dataclass

from src.adapters.twitch_api import TwitchAPIClient
from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    PatternRepository,
    ThreadRecord,
    ThreadRepository,
    TwitchAccountRepository,
    ReplyRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordReplyRequestedEvent,
    DiscordResultStyle,
    EventType,
)
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

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_REPLY_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordReplyRequestedEvent) -> None:
        try:
            result = await self._handle_action(event)
        except ValueError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
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
            denial_message = (
                "You do not have permission to add or remove auto-replies in this "
                "Discord channel."
            )
        else:
            required_permission = ObserverPermission.TOGGLE_REPLIES
            denial_message = (
                "You do not have permission to enable or disable auto-replies in this "
                "Discord channel."
            )

        thread = self._ensure_thread_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=required_permission,
            denial_message=denial_message,
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
            return DiscordCommandResult(
                title="Pattern Not Found",
                message="No ping or regex rule with that ID exists.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if event.action == "add":
            linked_account = (
                self.account_repository.get_by_account_id(thread.account_id)
                if thread.account_id is not None
                else None
            )
            if linked_account is None:
                return DiscordCommandResult(
                    title="No Linked Account",
                    message=(
                        "This Discord channel must link a Twitch account first with "
                        "`/account link` before auto-replies can be enabled."
                    ),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            message = (event.message or "").strip()
            if not message:
                raise ValueError("Please provide the reply message.")
            if len(message) > 500:
                raise ValueError("Twitch chat messages are limited to 500 characters.")
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is not None:
                return DiscordCommandResult(
                    title="Reply Already Exists",
                    message=(
                        "This pattern already has an attached auto-reply. Remove it "
                        "first before creating a new one."
                    ),
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
            return DiscordCommandResult(
                title="Auto-Reply Added",
                message=(
                    f"Added an auto-reply to pattern #{pattern.p_index}.\n"
                    "Mode: "
                    f"{'Reply to the matched message' if created.reply_as_reply else 'Send a separate Twitch message'}\n"
                    f"Message: {escape_discord_preserving_links(created.reply_message)}"
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "remove":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            cleared = self.reply_repository.remove_reply(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            assert cleared is not None
            return DiscordCommandResult(
                title="Auto-Reply Removed",
                message=f"Removed the auto-reply from pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "disable":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Disabled",
                    message="This auto-reply is already disabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=True,
            )
            assert disabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Disabled",
                message=f"Disabled the auto-reply on pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "enable":
            existing_reply = self.reply_repository.get_by_pattern(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
            )
            if existing_reply is None:
                return DiscordCommandResult(
                    title="No Auto-Reply Configured",
                    message="This pattern does not have an auto-reply.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            if not existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Enabled",
                    message="This auto-reply is already enabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.reply_repository.set_reply_disabled(
                thread_id=thread.thread_id,
                p_index=pattern.p_index,
                disabled=False,
            )
            assert enabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Enabled",
                message=f"Enabled the auto-reply on pattern `{pattern.p_index}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError("Unsupported reply action. Use add, remove, disable or enable.")

    async def _handle_adapter_event_action(
        self,
        thread: ThreadRecord,
        event: DiscordReplyRequestedEvent,
    ) -> DiscordCommandResult:
        if (
            self.adapter_event_repository is None
            or self.adapter_event_action_repository is None
        ):
            raise ValueError("External event auto-replies are not available in this runtime.")
        if event.adapter_event_id is None:
            raise ValueError("Please choose a configured live or offline event first.")

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
            return DiscordCommandResult(
                title="Event Trigger Not Found",
                message="That live or offline trigger is not configured in this Discord channel.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        state_label = STREAM_EVENT_KEY_TO_STATE.get(adapter_event.event_key)
        if (
            adapter_event.adapter_key != TWITCH_ADAPTER_KEY
            or adapter_event.subject_type != CHANNEL_SUBJECT_TYPE
            or state_label is None
        ):
            raise ValueError("Only tracked Twitch channel live/offline events can be used here.")

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
            linked_account = (
                self.account_repository.get_by_account_id(thread.account_id)
                if thread.account_id is not None
                else None
            )
            if linked_account is None:
                return DiscordCommandResult(
                    title="No Linked Account",
                    message=(
                        "This Discord channel must link a Twitch account first with "
                        "`/account link` before auto-replies can be enabled."
                    ),
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            message = (event.message or "").strip()
            if not message:
                raise ValueError("Please provide the reply message.")
            if len(message) > 500:
                raise ValueError("Twitch chat messages are limited to 500 characters.")
            created = self.adapter_event_action_repository.upsert_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                message_template=message,
                reply_as_reply=False,
            )
            return DiscordCommandResult(
                title="Auto-Reply Added",
                message=(
                    f"Added an auto-reply for `{channel_name}` when it goes {state_label}.\n"
                    f"Message: {escape_discord_preserving_links(created.message_template or '')}"
                ),
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if existing_reply is None:
            return DiscordCommandResult(
                title="No Auto-Reply Configured",
                message="This live/offline trigger does not have an auto-reply.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        if event.action == "remove":
            removed = self.adapter_event_action_repository.remove_action(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
            )
            assert removed is not None
            return DiscordCommandResult(
                title="Auto-Reply Removed",
                message=f"Removed the {state_label} auto-reply for `{channel_name}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "disable":
            if existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Disabled",
                    message="This auto-reply is already disabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            disabled_reply = self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=True,
            )
            assert disabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Disabled",
                message=f"Disabled the {state_label} auto-reply for `{channel_name}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "enable":
            if not existing_reply.disabled:
                return DiscordCommandResult(
                    title="Already Enabled",
                    message="This auto-reply is already enabled.",
                    style=DiscordResultStyle.INFO,
                    ephemeral=True,
                )
            enabled_reply = self.adapter_event_action_repository.set_action_disabled(
                event_id=adapter_event.event_id,
                action_type=TWITCH_SEND_MESSAGE_ACTION,
                disabled=False,
            )
            assert enabled_reply is not None
            return DiscordCommandResult(
                title="Auto-Reply Enabled",
                message=f"Enabled the {state_label} auto-reply for `{channel_name}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError("Unsupported reply action. Use add, remove, disable or enable.")

    def _ensure_thread_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_message: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message=denial_message,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread
