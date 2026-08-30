"""Direct service bundle used by Discord entrypoints and interactive UI flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.account_service import AccountCommandService
    from src.services.channel_command_service import ChannelCommandService
    from src.services.channel_live_state_service import ChannelEventCommandService
    from src.services.help_service import HelpCommandService
    from src.services.patterns.command_service import PatternCommandService
    from src.services.patterns.show_service import ShowCommandService
    from src.services.permission_service import PermissionCommandService
    from src.services.replies.reply_command_service import ReplyCommandService
    from src.services.support_command_service import SupportCommandService
    from src.services.thread_lifecycle_service import ThreadLifecycleService
    from src.services.ui_flow_service import DiscordUIFlowGuardService
    from src.services.user_command_service import UserCommandService
    from src.services.write_service import TwitchWriteCommandService


@dataclass(slots=True)
class DiscordServiceBundle:
    """Direct application-service references for Discord command and UI entrypoints."""

    thread: ThreadLifecycleService
    channel: ChannelCommandService
    user: UserCommandService
    pattern: PatternCommandService
    permission: PermissionCommandService
    account: AccountCommandService
    reply: ReplyCommandService
    help: HelpCommandService
    write: TwitchWriteCommandService
    show: ShowCommandService
    support: SupportCommandService
    channel_event: ChannelEventCommandService
    ui_flow_guard: DiscordUIFlowGuardService
