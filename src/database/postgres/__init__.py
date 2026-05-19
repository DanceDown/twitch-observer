"""Organized PostgreSQL persistence package."""

from .adapter_event_actions import PostgresAdapterEventActionRepository
from .adapter_events import PostgresAdapterEventRepository
from .patterns import PostgresPatternRepository
from .replies import PostgresReplyRepository
from .database import PostgresDatabase
from .messaging import PostgresMessageRepository
from .permissions import PostgresUserPermissionRepository
from .threads import (
    PostgresChannelRepository,
    PostgresThreadRepository,
    PostgresTrackedUserRepository,
)
from .twitch import (
    PostgresTwitchAccountRepository,
    PostgresTwitchDeviceFlowRepository,
    PostgresTwitchUserCacheRepository,
)

__all__ = [
    "PostgresAdapterEventActionRepository",
    "PostgresAdapterEventRepository",
    "PostgresPatternRepository",
    "PostgresReplyRepository",
    "PostgresChannelRepository",
    "PostgresDatabase",
    "PostgresMessageRepository",
    "PostgresThreadRepository",
    "PostgresTrackedUserRepository",
    "PostgresTwitchAccountRepository",
    "PostgresTwitchDeviceFlowRepository",
    "PostgresTwitchUserCacheRepository",
    "PostgresUserPermissionRepository",
]
