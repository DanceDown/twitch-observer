"""Business logic for `/show` configuration overviews."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import (
    AdapterEventActionRepository,
    AdapterEventRepository,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRepository,
    TrackedUserRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.discord_results import build_result, build_thread_result
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    ShowConfigurationCommand,
)
from src.localization import Localizer
from src.services.patterns.show_renderer import ShowSectionRenderer
from src.services.authz import thread_has_permission
from src.services.twitch_gateways import TwitchDirectoryGateway
from src.utils.permissions import ObserverPermission


@dataclass(slots=True)
class ShowCommandService:
    """Build user-facing overviews of stored configuration."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    twitch_api: TwitchDirectoryGateway
    tracked_user_repository: TrackedUserRepository | None = None
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None
    account_repository: TwitchAccountRepository | None = None
    device_flow_repository: TwitchDeviceFlowRepository | None = None
    _renderer: ShowSectionRenderer = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._renderer = ShowSectionRenderer(
            channel_repository=self.channel_repository,
            pattern_repository=self.pattern_repository,
            reply_repository=self.reply_repository,
            twitch_api=self.twitch_api,
            tracked_user_repository=self.tracked_user_repository,
            adapter_event_repository=self.adapter_event_repository,
            adapter_event_action_repository=self.adapter_event_action_repository,
            localizer=self.localizer,
            permission_repository=self.permission_repository,
            account_repository=self.account_repository,
            device_flow_repository=self.device_flow_repository,
        )

    async def handle_command(self, command: ShowConfigurationCommand) -> DiscordCommandResult:
        """Create an overview embed body for the selected sections."""
        thread = await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
        if thread is None:
            result = build_result(
                self.localizer,
                "results.show.not_joined",
                language=self.localizer.default_language,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        else:
            self._renderer.reset_resolution_cache()
            if not await thread_has_permission(
                thread=thread,
                requester_id=command.requester_id,
                permission_repository=self.permission_repository,
                required_permission=ObserverPermission.VIEW,
            ):
                result = build_thread_result(
                    self.localizer,
                    "results.show.permission_denied",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
                return result
            lines = []
            sections = self._normalize_sections(command.sections)
            if "channels" in sections:
                lines.append(await self._renderer.render_channels_section(thread))
            if "stream_pings" in sections:
                lines.append(await self._renderer.render_channel_events_section(thread))
            if "pings" in sections:
                lines.append(await self._renderer.render_patterns_section(thread))
            if "auto_replies" in sections:
                lines.append(await self._renderer.render_auto_replies_section(thread))
            if "users" in sections:
                lines.append(await self._renderer.render_users_section(thread))
            if "permissions" in sections:
                lines.append(await self._renderer.render_permissions_section(thread))
            thumbnail_url = None
            if "account" in sections:
                account_section, thumbnail_url = await self._renderer.render_account_section(thread)
                lines.append(account_section)
            result = build_thread_result(
                self.localizer,
                "results.show.overview",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                SECTION_LIST=[section for section in lines if section],
                thumbnail_url=thumbnail_url,
            )
        return result

    @staticmethod
    def _normalize_sections(raw_sections: tuple[str, ...]) -> tuple[str, ...]:
        """Validate the requested show sections against the supported set."""
        if not raw_sections:
            return ("channels",)

        allowed = {"channels", "stream_pings", "pings", "auto_replies", "users", "permissions", "account"}
        normalized = tuple(section for section in raw_sections if section in allowed)
        if normalized:
            return normalized
        return ("channels",)
