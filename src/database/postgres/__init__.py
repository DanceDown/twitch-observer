"""Organized PostgreSQL persistence package."""

from .adapter_event_actions import PostgresAdapterEventActionRepository
from .adapter_events import PostgresAdapterEventRepository
from .database import PostgresDatabase
from .messaging import PostgresMessageRepository
from .migrations import PostgresMigrationRunner
from .patterns import PostgresPatternRepository
from .permissions import PostgresUserPermissionRepository
from .replies import PostgresReplyRepository
from .support_tickets import PostgresSupportTicketRepository
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
    "PostgresSupportTicketRepository",
    "PostgresChannelRepository",
    "PostgresDatabase",
    "PostgresMessageRepository",
    "PostgresMigrationRunner",
    "PostgresThreadRepository",
    "PostgresTrackedUserRepository",
    "PostgresTwitchAccountRepository",
    "PostgresTwitchDeviceFlowRepository",
    "PostgresTwitchUserCacheRepository",
    "PostgresUserPermissionRepository",
]
