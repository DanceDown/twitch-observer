"""Organized PostgreSQL persistence package."""

from .automation import (
    PostgresAdapterEventActionRepository,
    PostgresAdapterEventRepository,
    PostgresPatternRepository,
    PostgresReplyRepository,
)
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
    "PostgresChannelRepository",
    "PostgresDatabase",
    "PostgresMessageRepository",
    "PostgresPatternRepository",
    "PostgresReplyRepository",
    "PostgresThreadRepository",
    "PostgresTrackedUserRepository",
    "PostgresTwitchAccountRepository",
    "PostgresTwitchDeviceFlowRepository",
    "PostgresTwitchUserCacheRepository",
    "PostgresUserPermissionRepository",
]
