from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.tests.chat_match_candidates import build_chat_match_candidates
from src.tests.dispatch_helpers import dispatch_pattern_command, dispatch_pattern_edit_command, dispatch_show_command
from src.gateways.twitch_api import TwitchChannelNotFoundError, TwitchUser
from src.database.connection import (
    ChatPatternCandidateRecord,
    ChannelRecord,
    ChannelRepository,
    MessageRepository,
    PatternRecord,
    PatternRepository,
    RecentMessageRecord,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRecord,
    TrackedUserRepository,
)
from types import SimpleNamespace
from src.events.event_types import DiscordResultStyle, TwitchChatMessageEvent
from src.localization import Localizer
from src.services.patterns import (
    PatternCommandService,
    PatternTrackingService,
    ShowCommandService,
    TrackingNotificationSender,
)
from src.services.patterns.display_index import PatternDisplayIndexResolver
from src.services.patterns.command_support import PatternCommandSupport


@dataclass
class InMemoryThreadRepository(ThreadRepository):
    threads_by_channel_id: dict[int, ThreadRecord] = field(default_factory=dict)
    next_thread_id: int = 1

    async def get_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.get(discord_channel_id)

    async def get_by_thread_id(self, thread_id: int) -> ThreadRecord | None:
        for thread in self.threads_by_channel_id.values():
            if thread.thread_id == thread_id:
                return thread
        return None

    async def create(self, owner_id: int, discord_channel_id: int) -> ThreadRecord:
        thread = ThreadRecord(
            thread_id=self.next_thread_id,
            owner_id=owner_id,
            discord_channel_id=discord_channel_id,
            enabled=True,
            color=None,
        )
        self.next_thread_id += 1
        self.threads_by_channel_id[discord_channel_id] = thread
        return thread

    async def delete_by_discord_channel_id(self, discord_channel_id: int) -> ThreadRecord | None:
        return self.threads_by_channel_id.pop(discord_channel_id, None)

    async def set_enabled(self, *, discord_channel_id: int, enabled: bool) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=enabled,
            color=thread.color,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated

    async def set_color(self, *, discord_channel_id: int, color: str | None) -> ThreadRecord | None:
        thread = self.threads_by_channel_id.get(discord_channel_id)
        if thread is None:
            return None
        updated = ThreadRecord(
            thread_id=thread.thread_id,
            owner_id=thread.owner_id,
            discord_channel_id=thread.discord_channel_id,
            enabled=thread.enabled,
            color=color,
        )
        self.threads_by_channel_id[discord_channel_id] = updated
        return updated


@dataclass
class InMemoryChannelRepository(ChannelRepository):
    channels_by_thread: dict[tuple[int, str], ChannelRecord] = field(default_factory=dict)

    async def get_by_thread_and_twitch_channel(self, thread_id: int, twitch_channel_id: str) -> ChannelRecord | None:
        return self.channels_by_thread.get((thread_id, twitch_channel_id))

    async def add_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread[(thread_id, twitch_channel_id)] = ChannelRecord(
            thread_id=thread_id,
            twitch_channel_id=twitch_channel_id,
            color=None,
        )

    async def remove_channel(self, thread_id: int, twitch_channel_id: str) -> None:
        self.channels_by_thread.pop((thread_id, twitch_channel_id), None)

    async def set_color(self, *, thread_id: int, twitch_channel_id: str, color: str | None) -> ChannelRecord | None:
        key = (thread_id, twitch_channel_id)
        existing = self.channels_by_thread.get(key)
        if existing is None:
            return None
        updated = ChannelRecord(
            thread_id=existing.thread_id,
            twitch_channel_id=existing.twitch_channel_id,
            color=color,
            is_live=existing.is_live,
            last_live_status_at=existing.last_live_status_at,
        )
        self.channels_by_thread[key] = updated
        return updated

    async def set_live_state_for_twitch_channel(self, *, twitch_channel_id: str, is_live: bool, changed_at: str | None) -> int:
        updated_rows = 0
        for key, existing in list(self.channels_by_thread.items()):
            if existing.twitch_channel_id != twitch_channel_id:
                continue
            self.channels_by_thread[key] = ChannelRecord(
                thread_id=existing.thread_id,
                twitch_channel_id=existing.twitch_channel_id,
                color=existing.color,
                is_live=is_live,
                last_live_status_at=changed_at,
            )
            updated_rows += 1
        return updated_rows

    async def count_threads_by_twitch_channel_id(self, twitch_channel_id: str) -> int:
        return sum(1 for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id)

    async def list_thread_ids_by_twitch_channel_id(self, twitch_channel_id: str) -> list[int]:
        return [record.thread_id for record in self.channels_by_thread.values() if record.twitch_channel_id == twitch_channel_id]

    async def list_channels_for_thread(self, thread_id: int) -> list[ChannelRecord]:
        return sorted(
            [record for record in self.channels_by_thread.values() if record.thread_id == thread_id],
            key=lambda record: record.twitch_channel_id,
        )


@dataclass
class InMemoryPatternRepository(PatternRepository):
    patterns: list[PatternRecord] = field(default_factory=list)
    next_pattern_id: int = 1
    thread_repository: ThreadRepository | None = None
    channel_repository: ChannelRepository | None = None
    tracked_user_repository: TrackedUserRepository | None = None
    reply_repository: ReplyRepository | None = None

    async def find_exact_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
    ) -> PatternRecord | None:
        for pattern in self.patterns:
            if (
                pattern.thread_id == thread_id
                and pattern.regex == regex
                and pattern.channel_scope_mode == channel_scope_mode
                and pattern.channel_scope_ids == tuple(sorted(channel_scope_ids))
                and pattern.user_scope_mode == user_scope_mode
                and pattern.user_scope_ids == tuple(sorted(user_scope_ids))
                and pattern.sub_state == sub_state
                and pattern.offline_state == offline_state
                and pattern.is_regex == is_regex
                and pattern.case_sensitive == case_sensitive
            ):
                return pattern
        return None

    async def add_pattern(
        self,
        *,
        thread_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        disabled: bool,
        priority: int,
    ) -> PatternRecord:
        record = PatternRecord(
            thread_id=thread_id,
            pattern_id=self.next_pattern_id,
            regex=regex,
            channel_scope_mode=channel_scope_mode,
            channel_scope_ids=tuple(sorted(channel_scope_ids)),
            user_scope_mode=user_scope_mode,
            user_scope_ids=tuple(sorted(user_scope_ids)),
            sub_state=sub_state,
            offline_state=offline_state,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            color=color,
            disabled=disabled,
            reply_message=None,
            reply_as_reply=False,
            priority=priority,
        )
        self.patterns.append(record)
        self.next_pattern_id += 1
        return record

    async def remove_pattern(self, *, thread_id: int, pattern_id: int) -> None:
        self.patterns = [pattern for pattern in self.patterns if not (pattern.thread_id == thread_id and pattern.pattern_id == pattern_id)]

    async def set_pattern_disabled(self, *, thread_id: int, pattern_id: int, disabled: bool) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.pattern_id == pattern_id:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    pattern_id=pattern.pattern_id,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=disabled,
                    priority=pattern.priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    async def set_pattern_priority(self, *, thread_id: int, pattern_id: int, priority: int) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.pattern_id == pattern_id:
                updated = PatternRecord(
                    thread_id=pattern.thread_id,
                    pattern_id=pattern.pattern_id,
                    regex=pattern.regex,
                    channel_scope_mode=pattern.channel_scope_mode,
                    channel_scope_ids=pattern.channel_scope_ids,
                    user_scope_mode=pattern.user_scope_mode,
                    user_scope_ids=pattern.user_scope_ids,
                    sub_state=pattern.sub_state,
                    offline_state=pattern.offline_state,
                    is_regex=pattern.is_regex,
                    case_sensitive=pattern.case_sensitive,
                    color=pattern.color,
                    disabled=pattern.disabled,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    async def update_pattern(
        self,
        *,
        thread_id: int,
        pattern_id: int,
        regex: str,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
        is_regex: bool,
        case_sensitive: bool,
        color: str | None,
        priority: int,
    ) -> PatternRecord | None:
        for index, pattern in enumerate(self.patterns):
            if pattern.thread_id == thread_id and pattern.pattern_id == pattern_id:
                updated = PatternRecord(
                    thread_id=thread_id,
                    pattern_id=pattern_id,
                    regex=regex,
                    channel_scope_mode=channel_scope_mode,
                    channel_scope_ids=tuple(sorted(channel_scope_ids)),
                    user_scope_mode=user_scope_mode,
                    user_scope_ids=tuple(sorted(user_scope_ids)),
                    sub_state=sub_state,
                    offline_state=offline_state,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    color=color,
                    disabled=pattern.disabled,
                    priority=priority,
                )
                self.patterns[index] = updated
                return updated
        return None

    async def list_active_patterns_for_thread(self, thread_id: int) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id and not pattern.disabled]
        return sorted(rows, key=lambda pattern: (-pattern.priority, pattern.pattern_id))

    async def list_chat_match_candidates(
        self,
        *,
        broadcaster_id: str,
        author_id: str,
        sender_is_sub: bool,
    ) -> list[ChatPatternCandidateRecord]:
        return await build_chat_match_candidates(
            patterns=self.patterns,
            thread_repository=self.thread_repository,
            channel_repository=self.channel_repository,
            reply_repository=self.reply_repository,
            tracked_user_repository=self.tracked_user_repository,
            broadcaster_id=broadcaster_id,
            author_id=author_id,
            sender_is_sub=sender_is_sub,
        )

    async def get_pattern_by_id(self, *, thread_id: int, pattern_id: int) -> PatternRecord | None:
        for pattern in self.patterns:
            if pattern.thread_id == thread_id and pattern.pattern_id == pattern_id:
                return pattern
        return None

    async def list_patterns_for_thread(self, thread_id: int, *, is_regex: bool | None = None) -> list[PatternRecord]:
        rows = [pattern for pattern in self.patterns if pattern.thread_id == thread_id]
        if is_regex is not None:
            rows = [pattern for pattern in rows if pattern.is_regex == is_regex]
        return sorted(rows, key=lambda pattern: pattern.pattern_id)

    async def count_channel_scope_references(self, *, thread_id: int, twitch_channel_id: str) -> int:
        return sum(1 for pattern in self.patterns if pattern.thread_id == thread_id and twitch_channel_id in pattern.channel_scope_ids)


@dataclass
class InMemoryReplyRepository(ReplyRepository):
    replies_by_pattern: dict[tuple[int, int], ReplyRecord] = field(default_factory=dict)

    async def get_by_pattern(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        return self.replies_by_pattern.get((thread_id, pattern_id))

    async def add_reply(self, *, thread_id: int, pattern_id: int, reply_message: str, reply_as_reply: bool) -> ReplyRecord | None:
        reply = ReplyRecord(
            thread_id=thread_id,
            pattern_id=pattern_id,
            reply_message=reply_message,
            reply_as_reply=reply_as_reply,
            disabled=False,
        )
        self.replies_by_pattern[(thread_id, pattern_id)] = reply
        return reply

    async def remove_reply(self, *, thread_id: int, pattern_id: int) -> ReplyRecord | None:
        return self.replies_by_pattern.pop((thread_id, pattern_id), None)

    async def list_replies_for_thread(self, thread_id: int, *, include_disabled: bool = True) -> list[ReplyRecord]:
        rows = [reply for reply in self.replies_by_pattern.values() if reply.thread_id == thread_id]
        if not include_disabled:
            rows = [reply for reply in rows if not reply.disabled]
        return sorted(rows, key=lambda reply: reply.pattern_id)

    async def disable_replies_for_thread(self, thread_id: int) -> int:
        return 0

    async def enable_replies_for_thread(self, thread_id: int) -> int:
        return 0


@dataclass
class InMemoryTrackedUserRepository(TrackedUserRepository):
    tracked_users: dict[tuple[int, str], TrackedUserRecord] = field(default_factory=dict)

    async def get_by_thread_and_twitch_user(self, thread_id: int, twitch_user_id: str) -> TrackedUserRecord | None:
        return self.tracked_users.get((thread_id, twitch_user_id))

    async def add_user(self, *, thread_id: int, twitch_user_id: str) -> TrackedUserRecord:
        record = TrackedUserRecord(thread_id=thread_id, twitch_user_id=twitch_user_id)
        self.tracked_users[(thread_id, twitch_user_id)] = record
        return record

    async def remove_user(self, *, thread_id: int, twitch_user_id: str) -> None:
        self.tracked_users.pop((thread_id, twitch_user_id), None)

    async def list_users_for_thread(self, thread_id: int) -> list[TrackedUserRecord]:
        return sorted(
            [record for record in self.tracked_users.values() if record.thread_id == thread_id],
            key=lambda record: record.twitch_user_id,
        )

    async def count_pattern_scope_references(self, *, thread_id: int, twitch_user_id: str) -> int:
        return 0


def wire_runtime_pattern_repository(
    repository: InMemoryPatternRepository,
    *,
    thread_repository: ThreadRepository,
    channel_repository: ChannelRepository,
    tracked_user_repository: TrackedUserRepository | None = None,
    reply_repository: ReplyRepository | None = None,
) -> None:
    repository.thread_repository = thread_repository
    repository.channel_repository = channel_repository
    repository.tracked_user_repository = tracked_user_repository
    repository.reply_repository = reply_repository


@dataclass
class InMemoryMessageRepository(MessageRepository):
    matched_thread_ids: list[tuple[int, str | None]] = field(default_factory=list)

    async def save_twitch_message(self, event: TwitchChatMessageEvent) -> None:
        return None

    async def list_recent_messages(self, *, since: datetime, limit: int) -> list[RecentMessageRecord]:
        return []

    async def list_recent_messages_for_channel(
        self,
        *,
        twitch_channel_id: str,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        return []

    async def mark_message_matched_in_thread(self, *, thread_id: int, event: TwitchChatMessageEvent) -> None:
        self.matched_thread_ids.append((thread_id, event.message_id))

    async def list_recent_messages_for_thread(
        self,
        *,
        thread_id: int,
        since: datetime,
        limit: int,
    ) -> list[RecentMessageRecord]:
        return []


@dataclass
class FakeTwitchAPI:
    users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    cached_users_by_login: dict[str, TwitchUser] = field(default_factory=dict)
    live_by_user_id: dict[str, bool] = field(default_factory=dict)
    error: Exception | None = None
    live_requests: list[str] = field(default_factory=list)
    login_requests: list[str] = field(default_factory=list)

    async def get_user_by_login(self, login: str) -> TwitchUser:
        if self.error is not None:
            raise self.error
        normalized = login.strip().lower()
        self.login_requests.append(normalized)
        try:
            return self.users_by_login[normalized]
        except KeyError as error:
            raise TwitchChannelNotFoundError(f"Unknown Twitch login: {normalized}") from error

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        if self.error is not None:
            raise self.error
        for user in self.users_by_login.values():
            if user.user_id == user_id:
                return user
        raise TwitchChannelNotFoundError(f"Unknown Twitch user id: {user_id}")

    async def get_channel_by_id(self, user_id: str) -> TwitchUser:
        return await self.get_user_by_id(user_id)

    async def refresh_channel_by_login(self, login: str) -> TwitchUser:
        return await self.get_user_by_login(login)

    def get_cached_user_by_login(self, login: str) -> TwitchUser | None:
        return self.cached_users_by_login.get(login.strip().lower())

    def get_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        for user in self.cached_users_by_login.values():
            if user.user_id == user_id:
                return user
        return None

    async def load_cached_user_by_id(self, user_id: str) -> TwitchUser | None:
        return self.get_cached_user_by_id(user_id)

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        rows: list[TwitchUser] = []
        for user_id in user_ids:
            try:
                rows.append(await self.get_user_by_id(user_id))
            except TwitchChannelNotFoundError:
                continue
        return tuple(rows)

    async def is_user_live(self, user_id: str) -> bool:
        self.live_requests.append(user_id)
        return self.live_by_user_id.get(user_id, False)


@dataclass
class FakeNotifier(TrackingNotificationSender):
    sent: list[tuple[int, object]] = field(default_factory=list)

    async def send_tracking_embed(self, discord_channel_id: int, embed, *, channel_login: str | None = None) -> None:
        self.sent.append((discord_channel_id, embed))


def _scope_summary_localizer() -> Localizer:
    return Localizer(
        catalogs={
            "english": {
                "results": {
                    "pattern": {
                        "added_result": {
                            "summary": {
                                "list": {
                                    "template": "{RAW:view.items}",
                                    "placeholders": {
                                        "view.items": {
                                            "list": {
                                                "item_format": "- {RAW:item}",
                                                "separator": "\n",
                                            }
                                        }
                                    },
                                },
                                "text": "Text: `{CODE:view.text}`",
                                "mode": "Mode: `{CODE:view.ping_mode}`",
                                "mode_value": {"word": "Word", "regex": "Regex"},
                                "scope": {
                                    "channel_only": {
                                        "template": "Only in {RAW:view.items}",
                                        "placeholders": {
                                            "view.items": {
                                                "list": {
                                                    "item_format": "[`{CODE:item.display_name}`](https://www.twitch.tv/{RAW:item.login})",
                                                    "separator": ", ",
                                                }
                                            }
                                        },
                                    },
                                    "user_only": {
                                        "template": "Only from {RAW:view.items}",
                                        "placeholders": {
                                            "view.items": {
                                                "list": {
                                                    "item_format": "[`{CODE:item.display_name}`](https://www.twitch.tv/{RAW:item.login})",
                                                    "separator": ", ",
                                                }
                                            }
                                        },
                                    },
                                },
                                "case_sensitive_yes": "Case-Sensitive: `Yes`",
                                "case_sensitive_no": "Case-Sensitive: `No`",
                                "priority": "Priority: `{CODE:view.priority}`",
                            }
                        },
                        "updated_result": {
                            "summary": {
                                "list": {
                                    "template": "{RAW:view.items}",
                                    "placeholders": {
                                        "view.items": {
                                            "list": {
                                                "item_format": "- {RAW:item}",
                                                "separator": "\n",
                                            }
                                        }
                                    },
                                },
                                "mode_value": {"word": "Word", "regex": "Regex"},
                                "scope": {
                                    "channel_all": "Every watched channel",
                                    "user_everyone": "Everyone",
                                    "channel_only": {
                                        "template": "Only in {RAW:view.items}",
                                        "placeholders": {
                                            "view.items": {
                                                "list": {
                                                    "item_format": "[`{CODE:item.display_name}`](https://www.twitch.tv/{RAW:item.login})",
                                                    "separator": ", ",
                                                }
                                            }
                                        },
                                    },
                                    "user_only": {
                                        "template": "Only from {RAW:view.items}",
                                        "placeholders": {
                                            "view.items": {
                                                "list": {
                                                    "item_format": "[`{CODE:item.display_name}`](https://www.twitch.tv/{RAW:item.login})",
                                                    "separator": ", ",
                                                }
                                            }
                                        },
                                    },
                                },
                                "where": "Where: From {RAW:view.before} to {RAW:view.after}",
                                "who": "Who: From {RAW:view.before} to {RAW:view.after}",
                            }
                        },
                    }
                }
            }
        }
    )


def test_pattern_presenter_keeps_scope_links_clickable_in_added_summary() -> None:
    support = PatternCommandSupport(
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=InMemoryPatternRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        localizer=_scope_summary_localizer(),
    )
    pattern = PatternRecord(
        thread_id=1,
        pattern_id=7,
        regex="hello",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="only_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )

    rendered = support.format_pattern_summary(
        pattern=pattern,
        channel_logins=({"display_name": "DanceDown", "login": "dancedown"},),
        user_logins=({"display_name": "Alice", "login": "alice"},),
        language="english",
        key_prefix="results.pattern.added_result.summary",
    )

    assert "[`DanceDown`](https://www.twitch.tv/dancedown)" in rendered
    assert "[`Alice`](https://www.twitch.tv/alice)" in rendered


def test_pattern_presenter_formats_updated_scope_change_without_wrapping_links_in_code() -> None:
    support = PatternCommandSupport(
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=InMemoryPatternRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        localizer=_scope_summary_localizer(),
    )
    before = PatternRecord(
        thread_id=1,
        pattern_id=7,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )
    after = PatternRecord(
        thread_id=1,
        pattern_id=7,
        regex="hello",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="only_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )

    rendered = support.format_pattern_changes(
        before=before,
        after=after,
        old_channel_logins=(),
        new_channel_logins=({"display_name": "DanceDown", "login": "dancedown"},),
        old_user_logins=(),
        new_user_logins=({"display_name": "Alice", "login": "alice"},),
        language="english",
        key_prefix="results.pattern.updated_result.summary",
    )

    assert "[`DanceDown`](https://www.twitch.tv/dancedown)" in rendered
    assert "[`Alice`](https://www.twitch.tv/alice)" in rendered


@pytest.mark.asyncio
async def test_ping_command_adds_pattern_with_selected_channel_scope() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(1, "42")
    pattern_repository = InMemoryPatternRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color="#123456",
        disabled=False,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert len(pattern_repository.patterns) == 1
    assert pattern_repository.patterns[0].channel_scope_mode == "only_selected"
    assert pattern_repository.patterns[0].channel_scope_ids == ("42",)


@pytest.mark.asyncio
async def test_ping_command_add_saves_explicit_priority() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=pattern_repository,
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=9,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].priority == 9


@pytest.mark.asyncio
async def test_pattern_command_removes_existing_regex_by_id() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="h.*o",
        pattern_id=None,
        is_regex=True,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="remove",
        pattern_text=None,
        pattern_id=1,
        is_regex=None,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.ephemeral is False
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_ping_command_disables_existing_pattern_by_id() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="disable",
        pattern_text=None,
        pattern_id=1,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=True,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].disabled is True


@pytest.mark.asyncio
async def test_ping_command_enables_disabled_pattern_by_id() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=True,
    )
    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="enable",
        pattern_text=None,
        pattern_id=1,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].disabled is False


@pytest.mark.asyncio
async def test_ping_command_requires_join_before_adding_patterns() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.ERROR
    assert result.ephemeral is True
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_pattern_priority_command_updates_existing_pattern_priority() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI()
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    result = await dispatch_pattern_edit_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        pattern_id=1,
        pattern_text=None,
        is_regex=None,
        channel_scope_mode=None,
        twitch_channel_logins=None,
        user_scope_mode=None,
        twitch_user_logins=None,
        sub_state=None,
        offline_state=None,
        case_sensitive=None,
        color=None,
        clear_color=False,
        priority=9,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].priority == 9


@pytest.mark.asyncio
async def test_pattern_edit_updates_existing_pattern_fields() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(1, "42")
    await channel_repository.add_channel(1, "43")
    pattern_repository = InMemoryPatternRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
            "other": TwitchUser(user_id="43", login="other", display_name="Other"),
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color="#123456",
        disabled=False,
    )

    result = await dispatch_pattern_edit_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        pattern_id=1,
        pattern_text="^hello there$",
        is_regex=True,
        channel_scope_mode="all_except_selected",
        twitch_channel_logins=("other",),
        user_scope_mode="only_selected",
        twitch_user_logins=("alice",),
        sub_state="subs",
        offline_state="online",
        case_sensitive=True,
        color=None,
        clear_color=True,
        priority=9,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    updated = pattern_repository.patterns[0]
    assert updated.regex == "^hello there$"
    assert updated.is_regex is True
    assert updated.channel_scope_mode == "all_except_selected"
    assert updated.channel_scope_ids == ("43",)
    assert updated.user_scope_mode == "only_selected"
    assert updated.user_scope_ids == ("7",)
    assert updated.sub_state == "subs"
    assert updated.offline_state == "online"
    assert updated.case_sensitive is True
    assert updated.color is None
    assert updated.priority == 9


@pytest.mark.asyncio
async def test_ping_command_rejects_selected_scope_channels_that_are_not_tracked() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(users_by_login={"example": TwitchUser(user_id="42", login="example", display_name="Example")})
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="only_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.ERROR
    assert result.ephemeral is True
    assert pattern_repository.patterns == []


@pytest.mark.asyncio
async def test_ping_command_supports_all_except_selected_scope() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(1, "42")
    await channel_repository.add_channel(1, "43")
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
            "other": TwitchUser(user_id="43", login="other", display_name="Other"),
        }
    )
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_except_selected",
        twitch_channel_logins=("example",),
        user_scope_mode="all_users",
        twitch_user_logins=(),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].channel_scope_mode == "all_except_selected"
    assert pattern_repository.patterns[0].channel_scope_ids == ("42",)


@pytest.mark.asyncio
async def test_ping_command_supports_selected_user_scope() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="only_selected",
        twitch_user_logins=("alice",),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].user_scope_mode == "only_selected"
    assert pattern_repository.patterns[0].user_scope_ids == ("7",)


@pytest.mark.asyncio
async def test_ping_command_supports_all_except_selected_users() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    await thread_repository.create(owner_id=200, discord_channel_id=100)
    pattern_repository = InMemoryPatternRepository()
    channel_repository = InMemoryChannelRepository()
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
        }
    )
    event_bus.pattern = PatternCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_pattern_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        action="add",
        pattern_text="hello",
        pattern_id=None,
        is_regex=False,
        channel_scope_mode="all_tracked",
        twitch_channel_logins=(),
        user_scope_mode="all_except_selected",
        twitch_user_logins=("alice",),
        sub_state="all",
        offline_state="both",
        case_sensitive=False,
        color=None,
        disabled=False,
    )

    assert result.style == DiscordResultStyle.SUCCESS
    assert pattern_repository.patterns[0].user_scope_mode == "all_except_selected"
    assert pattern_repository.patterns[0].user_scope_ids == ("7",)


@pytest.mark.asyncio
async def test_show_command_lists_channels_and_all_pattern_types_together() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=2,
    )
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="^hello$",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=True,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )
    twitch_api = FakeTwitchAPI(
        users_by_login={
            "example": TwitchUser(user_id="42", login="example", display_name="Example"),
        }
    )
    event_bus.show = ShowCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
        twitch_api=twitch_api,  # type: ignore[arg-type]
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("channels", "pings"),
    )

    assert result.ephemeral is True
    assert result.style == DiscordResultStyle.INFO
    assert result.message


@pytest.mark.asyncio
async def test_show_command_lists_tracked_users_with_links() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    tracked_user_repository = InMemoryTrackedUserRepository()
    await tracked_user_repository.add_user(thread_id=thread.thread_id, twitch_user_id="7")
    event_bus.show = ShowCommandService(
        thread_repository=thread_repository,
        channel_repository=InMemoryChannelRepository(),
        pattern_repository=InMemoryPatternRepository(),
        reply_repository=InMemoryReplyRepository(),
        twitch_api=FakeTwitchAPI(
            users_by_login={
                "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
            }
        ),  # type: ignore[arg-type]
        tracked_user_repository=tracked_user_repository,
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("users",),
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert result.message


@pytest.mark.asyncio
async def test_show_command_renders_where_and_who_as_bullets() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    tracked_user_repository = InMemoryTrackedUserRepository()
    await tracked_user_repository.add_user(thread_id=thread.thread_id, twitch_user_id="7")
    pattern_repository = InMemoryPatternRepository(
        patterns=[
            PatternRecord(
                thread_id=thread.thread_id,
                pattern_id=1,
                regex="hello",
                channel_scope_mode="only_selected",
                channel_scope_ids=("42",),
                user_scope_mode="only_selected",
                user_scope_ids=("7",),
                sub_state="all",
                offline_state="both",
                is_regex=False,
                case_sensitive=False,
                color=None,
                disabled=False,
                priority=0,
            )
        ]
    )
    event_bus.show = ShowCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
        twitch_api=FakeTwitchAPI(
            users_by_login={
                "example": TwitchUser(user_id="42", login="example", display_name="Example"),
                "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
            }
        ),  # type: ignore[arg-type]
        tracked_user_repository=tracked_user_repository,
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("pings",),
    )

    assert "https://www.twitch.tv/example" in result.message
    assert "https://www.twitch.tv/alice" in result.message


@pytest.mark.asyncio
async def test_tracking_service_sends_embed_for_matching_ping_with_pattern_color() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            color="#ffffff",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1
    sent_channel_id, _ = notifier.sent[0]
    assert sent_channel_id == 1000


@pytest.mark.asyncio
async def test_tracking_service_refreshes_missing_author_profile_image_once() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    twitch_api = FakeTwitchAPI(
        cached_users_by_login={"alice": TwitchUser(user_id="7", login="alice", display_name="Alice", profile_image_url=None)},
        users_by_login={
            "alice": TwitchUser(
                user_id="7",
                login="alice",
                display_name="Alice",
                profile_image_url="https://example.test/alice.png",
            )
        },
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert twitch_api.login_requests == ["alice"]
    _, embed = notifier.sent[0]
    assert embed.author.icon_url == "https://example.test/alice.png"


@pytest.mark.asyncio
async def test_tracking_service_sends_embed_for_case_sensitive_ping_match() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="test",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=True,
        color=None,
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="test",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_tracking_service_uses_highest_priority_match_and_stops_after_first_match() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#111111",
        disabled=False,
        priority=1,
    )
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello there",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#222222",
        disabled=False,
        priority=9,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there everyone",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1
    sent_channel_id, _ = notifier.sent[0]
    assert sent_channel_id == 1000


@pytest.mark.asyncio
async def test_tracking_service_skips_normal_embed_when_pattern_has_enabled_reply() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    reply_repository = InMemoryReplyRepository()
    await reply_repository.add_reply(thread_id=thread.thread_id, pattern_id=1, reply_message="Hi there", reply_as_reply=True)
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        reply_repository=reply_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
        reply_repository=reply_repository,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []


@pytest.mark.asyncio
async def test_show_command_lists_patterns_in_creation_order() -> None:
    event_bus = SimpleNamespace()
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=100)
    channel_repository = InMemoryChannelRepository()
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="general",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=1,
    )
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="specific",
        channel_scope_mode="only_selected",
        channel_scope_ids=("42",),
        user_scope_mode="only_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=8,
    )
    event_bus.show = ShowCommandService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        reply_repository=InMemoryReplyRepository(),
        twitch_api=FakeTwitchAPI(
            users_by_login={
                "example": TwitchUser(user_id="42", login="example", display_name="Example"),
                "alice": TwitchUser(user_id="7", login="alice", display_name="Alice"),
            }
        ),  # type: ignore[arg-type]
    )

    result = await dispatch_show_command(
        event_bus,
        discord_channel_id=100,
        requester_id=200,
        sections=("pings",),
    )

    assert result.style == DiscordResultStyle.INFO
    assert result.ephemeral is True
    assert result.message
    assert result.message.index("general") < result.message.index("specific")


@pytest.mark.asyncio
async def test_display_index_stays_stable_when_pattern_priority_changes() -> None:
    pattern_repository = InMemoryPatternRepository()
    first = await pattern_repository.add_pattern(
        thread_id=1,
        regex="first",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=1,
    )
    second = await pattern_repository.add_pattern(
        thread_id=1,
        regex="second",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=9,
    )
    resolver = PatternDisplayIndexResolver(pattern_repository)

    assert await resolver.build_index_map(1) == {first.pattern_id: 1, second.pattern_id: 2}

    await pattern_repository.set_pattern_priority(thread_id=1, pattern_id=first.pattern_id, priority=9)
    await pattern_repository.set_pattern_priority(thread_id=1, pattern_id=second.pattern_id, priority=0)

    assert await resolver.build_index_map(1) == {first.pattern_id: 1, second.pattern_id: 2}


@pytest.mark.asyncio
async def test_tracking_service_respects_all_except_selected_user_scope() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_except_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            color="#ffffff",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []


@pytest.mark.asyncio
async def test_tracking_service_respects_all_tracked_except_selected_user_scope() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    tracked_user_repository = InMemoryTrackedUserRepository()
    await tracked_user_repository.add_user(thread_id=thread.thread_id, twitch_user_id="7")
    await tracked_user_repository.add_user(thread_id=thread.thread_id, twitch_user_id="8")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_tracked_except_selected",
        user_scope_ids=("7",),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        tracked_user_repository=tracked_user_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="bob",
            author_display_name="Bob",
            author_id="8",
            broadcaster_id="42",
            color="#ffffff",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_tracking_service_skips_disabled_thread() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    await thread_repository.set_enabled(discord_channel_id=1000, enabled=False)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="both",
        is_regex=False,
        case_sensitive=False,
        color="#123456",
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=FakeTwitchAPI(),  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert notifier.sent == []


@pytest.mark.asyncio
async def test_tracking_service_uses_persisted_channel_live_state_without_twitch_live_lookup() -> None:
    thread_repository = InMemoryThreadRepository()
    thread = await thread_repository.create(owner_id=200, discord_channel_id=1000)
    channel_repository = InMemoryChannelRepository()
    await channel_repository.add_channel(thread.thread_id, "42")
    await channel_repository.set_live_state_for_twitch_channel(twitch_channel_id="42", is_live=True, changed_at="now")
    pattern_repository = InMemoryPatternRepository()
    await pattern_repository.add_pattern(
        thread_id=thread.thread_id,
        regex="hello",
        channel_scope_mode="all_tracked",
        channel_scope_ids=(),
        user_scope_mode="all_users",
        user_scope_ids=(),
        sub_state="all",
        offline_state="online",
        is_regex=False,
        case_sensitive=False,
        color=None,
        disabled=False,
        priority=0,
    )
    wire_runtime_pattern_repository(
        pattern_repository,
        thread_repository=thread_repository,
        channel_repository=channel_repository,
    )
    twitch_api = FakeTwitchAPI()
    notifier = FakeNotifier()
    service = PatternTrackingService(
        thread_repository=thread_repository,
        channel_repository=channel_repository,
        pattern_repository=pattern_repository,
        message_repository=InMemoryMessageRepository(),
        twitch_api=twitch_api,  # type: ignore[arg-type]
        notifier=notifier,
    )

    await service.handle_chat_message(
        TwitchChatMessageEvent(
            channel_login="example",
            author_login="alice",
            author_display_name="Alice",
            author_id="7",
            broadcaster_id="42",
            content="hello there",
            sent_at=datetime.now(UTC),
            raw_tags={"badges": ""},
        )
    )

    assert len(notifier.sent) == 1
    assert twitch_api.live_requests == []
