"""Bundle type for Discord UI query services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_queries import AdapterEventQueryService
    from .pattern_queries import PatternQueryService
    from .reply_queries import ReplyQueryService
    from .tracked_channel_queries import TrackedChannelQueryService
    from .tracked_user_queries import TrackedUserQueryService
    from .write_queries import WriteQueryService


@dataclass(slots=True)
class DiscordUIQueryBundle:
    """Container for every read-side service used by Discord UI flows."""

    channels: TrackedChannelQueryService
    patterns: PatternQueryService
    users: TrackedUserQueryService
    replies: ReplyQueryService
    events: AdapterEventQueryService
    write: WriteQueryService
