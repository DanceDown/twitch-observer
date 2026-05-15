"""Service-owned guards for Discord UI flow steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import (
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
    DiscordResultStyle,
    DiscordUIFlowDecision,
    DiscordUIFlowRequestedEvent,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission


@dataclass(slots=True)
class DiscordUIFlowGuardService:
    """Decide whether Discord may render a flow step before opening UI."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_UI_FLOW_REQUESTED, self.handle_request)

    def handle_request(self, event: DiscordUIFlowRequestedEvent) -> None:
        decision = self._decide(event)
        if not event.result_future.done():
            event.result_future.set_result(decision)

    def _decide(self, event: DiscordUIFlowRequestedEvent) -> DiscordUIFlowDecision:
        thread = None if event.discord_channel_id is None else self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            return self._blocked(
                event,
                self.localizer.result("results.not_joined", style=DiscordResultStyle.ERROR, ephemeral=True),
            )

        required = self._required_permission(event.flow, event.step)
        if required and not self._has_any_permission(thread, event.requester_id, required):
            return self._blocked(event, self._permission_result(thread, event.flow, event.step))

        if event.flow == "account" and event.requester_id != thread.owner_id:
            return self._blocked(
                event,
                self.localizer.thread_result(
                    "results.account.owner_denied",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                ),
            )

        if event.flow in {"live", "offline", "write"} and not self.channel_repository.list_channels_for_thread(thread.thread_id):
            key = "discord.write_ui.errors.no_channels" if event.flow == "write" else "discord.live_state_ui.errors.no_channels"
            return self._blocked(
                event,
                self.localizer.thread_result(key, thread=thread, style=DiscordResultStyle.ERROR, ephemeral=True),
            )

        if event.flow == "reply" and event.step in {"add_pattern", "add_event"}:
            account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if account is None or not account.access_token:
                return self._blocked(
                    event,
                    self.localizer.thread_result(
                        "results.reply.no_linked_account",
                        thread=thread,
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )

        if event.flow == "write":
            account = self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
            if account is None or not account.access_token:
                return self._blocked(
                    event,
                    self.localizer.thread_result(
                        "results.write.no_linked_account",
                        thread=thread,
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )

        return DiscordUIFlowDecision(flow=event.flow, step=event.step, open_ui=True)

    def _required_permission(self, flow: str, step: str) -> tuple[ObserverPermission, ...]:
        if flow == "thread":
            if step == "leave":
                return (ObserverPermission.LEAVE_CONTEXT,)
            if step == "color":
                return (ObserverPermission.CONTROL_OBSERVER,)
            return ()
        if flow == "channel":
            return (ObserverPermission.MANAGE_CHANNELS,)
        if flow == "user":
            return (ObserverPermission.MANAGE_PATTERNS,)
        if flow == "show":
            return (ObserverPermission.VIEW,)
        if flow == "permission":
            return (ObserverPermission.MANAGE_PERMISSIONS,)
        if flow == "account":
            return (ObserverPermission.CONTROL_OBSERVER,)
        if flow in {"live", "offline"}:
            return (ObserverPermission.MANAGE_CHANNELS,)
        if flow == "write":
            return (ObserverPermission.SEND_TWITCH_MESSAGES,)
        if flow == "ping":
            if step in {"root"}:
                return (ObserverPermission.MANAGE_PATTERNS, ObserverPermission.TOGGLE_PATTERNS)
            if step in {"disable", "enable"}:
                return (ObserverPermission.TOGGLE_PATTERNS,)
            return (ObserverPermission.MANAGE_PATTERNS,)
        if flow == "reply":
            if step in {"disable", "enable"}:
                return (ObserverPermission.TOGGLE_REPLIES,)
            if step == "root":
                return (ObserverPermission.MANAGE_REPLIES, ObserverPermission.TOGGLE_REPLIES)
            return (ObserverPermission.MANAGE_REPLIES,)
        return ()

    def _permission_result(self, thread: ThreadRecord, flow: str, step: str) -> DiscordCommandResult:
        key = {
            "thread": (
                "results.thread.leave_denied"
                if step == "leave"
                else "results.thread.color_denied" if step == "color" else None
            ),
            "channel": "results.channel.permission_denied",
            "user": "results.user.permission_denied",
            "show": "results.show.permission_denied",
            "write": "results.write.permission_denied",
            "permission": "results.permission.permission_denied",
            "account": "results.account.permission_denied",
            "live": "results.channel_event.permission_denied",
            "offline": "results.channel_event.permission_denied",
        }.get(flow)
        if flow == "ping":
            key = (
                "results.pattern.toggle_permission_denied" if step in {"disable", "enable"} else "results.pattern.manage_permission_denied"
            )
        if flow == "reply":
            key = "results.reply.toggle_permission_denied" if step in {"disable", "enable"} else "results.reply.manage_permission_denied"
        if key is None:
            return self.localizer.thread_result(
                "results.permission_denied",
                thread=thread,
                DETAIL=self.localizer.text("results.permission.generic_denied", language=thread.language),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return self.localizer.thread_result(key, thread=thread, style=DiscordResultStyle.ERROR, ephemeral=True)

    def _has_any_permission(
        self,
        thread: ThreadRecord,
        requester_id: int,
        permissions: tuple[ObserverPermission, ...],
    ) -> bool:
        return any(
            thread_has_permission(
                thread=thread,
                requester_id=requester_id,
                permission_repository=self.permission_repository,
                required_permission=permission,
            )
            for permission in permissions
        )

    @staticmethod
    def _blocked(event: DiscordUIFlowRequestedEvent, result: DiscordCommandResult) -> DiscordUIFlowDecision:
        return DiscordUIFlowDecision(flow=event.flow, step=event.step, open_ui=False, result=result)

