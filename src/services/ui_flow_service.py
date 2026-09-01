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
from src.discord_results import build_result, build_thread_result
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.events.ui_flow import DiscordUIFlowDecision, RequestUIFlowCommand, UIFlowKind, UIFlowStep
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.utils.permissions import ObserverPermission

_TOGGLE_STEPS = {UIFlowStep.DISABLE, UIFlowStep.ENABLE}
_SIMPLE_FLOW_PERMISSIONS: dict[UIFlowKind, tuple[ObserverPermission, ...]] = {
    UIFlowKind.CHANNEL: (ObserverPermission.MANAGE_CHANNELS,),
    UIFlowKind.USER: (ObserverPermission.MANAGE_PATTERNS,),
    UIFlowKind.SHOW: (ObserverPermission.VIEW,),
    UIFlowKind.PERMISSION: (ObserverPermission.MANAGE_PERMISSIONS,),
    UIFlowKind.ACCOUNT: (ObserverPermission.CONTROL_OBSERVER,),
    UIFlowKind.LIVE: (ObserverPermission.MANAGE_CHANNELS,),
    UIFlowKind.WRITE: (ObserverPermission.SEND_TWITCH_MESSAGES,),
}
_THREAD_STEP_PERMISSIONS: dict[UIFlowStep, tuple[ObserverPermission, ...]] = {
    UIFlowStep.LEAVE: (ObserverPermission.LEAVE_CONTEXT,),
    UIFlowStep.COLOR: (ObserverPermission.CONTROL_OBSERVER,),
}
_PATTERN_STEP_PERMISSIONS: dict[UIFlowStep, tuple[ObserverPermission, ...]] = {
    UIFlowStep.ROOT: (ObserverPermission.MANAGE_PATTERNS, ObserverPermission.TOGGLE_PATTERNS),
    UIFlowStep.DISABLE: (ObserverPermission.TOGGLE_PATTERNS,),
    UIFlowStep.ENABLE: (ObserverPermission.TOGGLE_PATTERNS,),
}
_REPLY_STEP_PERMISSIONS: dict[UIFlowStep, tuple[ObserverPermission, ...]] = {
    UIFlowStep.ROOT: (ObserverPermission.MANAGE_REPLIES, ObserverPermission.TOGGLE_REPLIES),
    UIFlowStep.DISABLE: (ObserverPermission.TOGGLE_REPLIES,),
    UIFlowStep.ENABLE: (ObserverPermission.TOGGLE_REPLIES,),
}
_SIMPLE_PERMISSION_RESULT_KEYS: dict[UIFlowKind, str] = {
    UIFlowKind.CHANNEL: "results.channel.permission_denied",
    UIFlowKind.USER: "results.user.permission_denied",
    UIFlowKind.SHOW: "results.show.permission_denied",
    UIFlowKind.WRITE: "results.write.permission_denied",
    UIFlowKind.PERMISSION: "results.permission.permission_denied",
    UIFlowKind.ACCOUNT: "results.account.permission_denied",
    UIFlowKind.LIVE: "results.channel_event.permission_denied",
}
_THREAD_PERMISSION_RESULT_KEYS: dict[UIFlowStep, str] = {
    UIFlowStep.LEAVE: "results.thread.leave_denied",
    UIFlowStep.COLOR: "results.thread.color_denied",
}


@dataclass(slots=True)
class DiscordUIFlowGuardService:
    """Decide whether Discord may render a flow step before opening UI."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    account_repository: TwitchAccountRepository
    permission_repository: UserPermissionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    async def decide(self, event: RequestUIFlowCommand) -> DiscordUIFlowDecision:
        """Return whether a Discord UI flow step may open."""
        return await self._decide(event)

    async def _decide(self, event: RequestUIFlowCommand) -> DiscordUIFlowDecision:
        thread = (
            None if event.discord_channel_id is None else await self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        )
        decision: DiscordUIFlowDecision | None = None
        if thread is None:
            decision = self._blocked(
                event,
                build_result(self.localizer, "results.ui_flow.not_joined", style=DiscordResultStyle.ERROR, ephemeral=True),
            )
        else:
            required = self._required_permission(event.flow, event.step)
            if required and not await self._has_any_permission(thread, event.requester_id, required):
                decision = self._blocked(event, self._permission_result(thread, event.flow, event.step))
            elif event.flow is UIFlowKind.ACCOUNT and event.requester_id != thread.owner_id:
                decision = self._blocked(
                    event,
                    build_thread_result(
                        self.localizer,
                        "results.account.owner_denied",
                        thread=thread,
                        style=DiscordResultStyle.ERROR,
                        ephemeral=True,
                    ),
                )
            elif event.flow in {UIFlowKind.LIVE, UIFlowKind.WRITE} and not await self.channel_repository.list_channels_for_thread(
                thread.thread_id
            ):
                key = (
                    "discord.write_ui.errors.no_channels" if event.flow is UIFlowKind.WRITE else "discord.live_state_ui.errors.no_channels"
                )
                decision = self._blocked(
                    event,
                    build_thread_result(self.localizer, key, thread=thread, style=DiscordResultStyle.ERROR, ephemeral=True),
                )
            elif event.flow is UIFlowKind.REPLY and event.step in {UIFlowStep.ADD_PATTERN, UIFlowStep.ADD_EVENT}:
                account = await self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
                if account is None or not account.access_token:
                    decision = self._blocked(
                        event,
                        build_thread_result(
                            self.localizer,
                            "results.reply.no_linked_account",
                            thread=thread,
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        ),
                    )
            elif event.flow is UIFlowKind.WRITE:
                account = await self.account_repository.get_by_account_id(thread.account_id) if thread.account_id is not None else None
                if account is None or not account.access_token:
                    decision = self._blocked(
                        event,
                        build_thread_result(
                            self.localizer,
                            "results.write.no_linked_account",
                            thread=thread,
                            style=DiscordResultStyle.ERROR,
                            ephemeral=True,
                        ),
                    )

        if decision is not None:
            return decision
        return DiscordUIFlowDecision(flow=event.flow, step=event.step, open_ui=True)

    def _required_permission(self, flow: UIFlowKind, step: UIFlowStep) -> tuple[ObserverPermission, ...]:
        if flow is UIFlowKind.THREAD:
            return _THREAD_STEP_PERMISSIONS.get(step, ())
        if flow is UIFlowKind.PATTERN:
            return _PATTERN_STEP_PERMISSIONS.get(step, (ObserverPermission.MANAGE_PATTERNS,))
        if flow is UIFlowKind.REPLY:
            return _REPLY_STEP_PERMISSIONS.get(step, (ObserverPermission.MANAGE_REPLIES,))
        return _SIMPLE_FLOW_PERMISSIONS.get(flow, ())

    def _permission_result(self, thread: ThreadRecord, flow: UIFlowKind, step: UIFlowStep) -> DiscordCommandResult:
        key = _THREAD_PERMISSION_RESULT_KEYS.get(step) if flow is UIFlowKind.THREAD else _SIMPLE_PERMISSION_RESULT_KEYS.get(flow)
        if flow is UIFlowKind.PATTERN:
            key = "results.pattern.toggle_permission_denied" if step in _TOGGLE_STEPS else "results.pattern.manage_permission_denied"
        if flow is UIFlowKind.REPLY:
            key = "results.reply.toggle_permission_denied" if step in _TOGGLE_STEPS else "results.reply.manage_permission_denied"
        if key is None:
            return build_thread_result(
                self.localizer,
                "results.ui_flow.permission_denied",
                thread=thread,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
                sources={
                    "view": {
                        "detail": self.localizer.text(
                            "results.ui_flow.permission_detail.generic",
                            language=thread.language,
                        )
                    }
                },
            )
        return build_thread_result(self.localizer, key, thread=thread, style=DiscordResultStyle.ERROR, ephemeral=True)

    async def _has_any_permission(
        self,
        thread: ThreadRecord,
        requester_id: int,
        permissions: tuple[ObserverPermission, ...],
    ) -> bool:
        for permission in permissions:
            if await thread_has_permission(
                thread=thread,
                requester_id=requester_id,
                permission_repository=self.permission_repository,
                required_permission=permission,
            ):
                return True
        return False

    @staticmethod
    def _blocked(event: RequestUIFlowCommand, result: DiscordCommandResult) -> DiscordUIFlowDecision:
        return DiscordUIFlowDecision(flow=event.flow, step=event.step, open_ui=False, result=result)
