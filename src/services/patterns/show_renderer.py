"""Rendering helpers for `/show` configuration overviews."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import (
    AdapterEventActionRepository,
    ChannelRepository,
    PatternRepository,
    ReplyRepository,
    ThreadRecord,
    TrackedUserRepository,
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.localization import Localizer
from src.services.show import (
    ShowAccountRenderer,
    ShowAutoRepliesRenderer,
    ShowChannelEventsRenderer,
    ShowChannelsRenderer,
    ShowPatternSectionRenderer,
    ShowPermissionsRenderer,
    ShowTwitchSubjectResolver,
    ShowUsersRenderer,
)
from src.services.twitch_gateways import TwitchDirectoryGateway


@dataclass(slots=True)
class ShowSectionRenderer:
    """Coordinate focused `/show` section renderers while keeping the public API stable."""

    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository | None
    twitch_api: TwitchDirectoryGateway
    tracked_user_repository: TrackedUserRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)
    permission_repository: UserPermissionRepository | None = None
    account_repository: TwitchAccountRepository | None = None
    device_flow_repository: TwitchDeviceFlowRepository | None = None
    _resolver: ShowTwitchSubjectResolver = field(init=False, repr=False)
    _channels: ShowChannelsRenderer = field(init=False, repr=False)
    _channel_events: ShowChannelEventsRenderer = field(init=False, repr=False)
    _patterns: ShowPatternSectionRenderer = field(init=False, repr=False)
    _auto_replies: ShowAutoRepliesRenderer = field(init=False, repr=False)
    _users: ShowUsersRenderer = field(init=False, repr=False)
    _permissions: ShowPermissionsRenderer = field(init=False, repr=False)
    _account: ShowAccountRenderer = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Create focused section renderers that share one Twitch resolver cache."""
        self._resolver = ShowTwitchSubjectResolver(self.twitch_api)
        self._channels = ShowChannelsRenderer(
            channel_repository=self.channel_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )
        self._channel_events = ShowChannelEventsRenderer(
            channel_repository=self.channel_repository,
            adapter_event_action_repository=self.adapter_event_action_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )
        self._patterns = ShowPatternSectionRenderer(
            pattern_repository=self.pattern_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )
        self._auto_replies = ShowAutoRepliesRenderer(
            pattern_repository=self.pattern_repository,
            reply_repository=self.reply_repository,
            adapter_event_action_repository=self.adapter_event_action_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )
        self._users = ShowUsersRenderer(
            tracked_user_repository=self.tracked_user_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )
        self._permissions = ShowPermissionsRenderer(
            permission_repository=self.permission_repository,
            localizer=self.localizer,
        )
        self._account = ShowAccountRenderer(
            account_repository=self.account_repository,
            device_flow_repository=self.device_flow_repository,
            resolver=self._resolver,
            localizer=self.localizer,
        )

    def reset_resolution_cache(self) -> None:
        """Clear cached Twitch name resolutions before a fresh `/show` render."""
        self._resolver.reset()

    async def render_channels_section(self, thread: ThreadRecord) -> str:
        """Render tracked Twitch channels for a `/show` response."""
        return await self._channels.render(thread)

    async def render_channel_events_section(self, thread: ThreadRecord) -> str:
        """Render live/offline channel-event configuration for `/show`."""
        return await self._channel_events.render(thread)

    async def render_patterns_section(self, thread: ThreadRecord) -> str:
        """Render ping and regex patterns for `/show`."""
        return await self._patterns.render(thread)

    async def render_auto_replies_section(self, thread: ThreadRecord) -> str:
        """Render pattern and live/offline auto-replies for `/show`."""
        return await self._auto_replies.render(thread)

    async def render_users_section(self, thread: ThreadRecord) -> str:
        """Render tracked Twitch users for `/show`."""
        return await self._users.render(thread)

    async def render_permissions_section(self, thread: ThreadRecord) -> str:
        """Render explicit Discord permission grants for `/show`."""
        return await self._permissions.render(thread)

    async def render_account_section(self, thread: ThreadRecord) -> tuple[str, str | None]:
        """Render linked Twitch account state plus an optional thumbnail."""
        return await self._account.render(thread)
