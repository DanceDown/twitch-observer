from __future__ import annotations

"""Business logic for `/ping` add/edit/remove requests."""

import re
from dataclasses import dataclass
import logging

from src.adapters.twitch_api import (
    TwitchAPIClient,
    TwitchAPIConfigurationError,
    TwitchAPIError,
    TwitchChannelNotFoundError,
)
from src.database.connection import (
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    TrackedUserRepository,
    ThreadRecord,
    ThreadRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordPatternEditRequestedEvent,
    DiscordPatternRequestedEvent,
    DiscordResultStyle,
    EventType,
)
from src.services.authz import thread_has_permission
from src.utils.discord_embeds import escape_discord_text
from src.utils.permissions import ObserverPermission

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PatternCommandService:
    """Handle `/ping` add/edit/remove requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    tracked_user_repository: TrackedUserRepository | None = None
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        """Subscribe the service to incoming Discord pattern command events."""
        self.event_bus.subscribe(EventType.DISCORD_PATTERN_REQUESTED, self.handle_request)
        self.event_bus.subscribe(
            EventType.DISCORD_PATTERN_EDIT_REQUESTED,
            self.handle_edit_request,
        )

    async def handle_request(self, event: DiscordPatternRequestedEvent) -> None:
        """Handle one add/remove request and complete the command result future."""
        try:
            result = await self._handle_action(event)
        except (
            TwitchAPIConfigurationError,
            TwitchChannelNotFoundError,
            ValueError,
        ) as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except re.error as error:
            result = DiscordCommandResult(
                title="Regex Error",
                message=f"Invalid regex: {error}",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling pattern command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def handle_edit_request(self, event: DiscordPatternEditRequestedEvent) -> None:
        """Handle one edit request and complete the command result future."""
        try:
            result = await self._edit_pattern(event)
        except (
            TwitchAPIConfigurationError,
            TwitchChannelNotFoundError,
            ValueError,
        ) as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except re.error as error:
            result = DiscordCommandResult(
                title="Regex Error",
                message=f"Invalid regex: {error}",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling pattern edit command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(
        self,
        event: DiscordPatternRequestedEvent,
    ) -> DiscordCommandResult:
        if event.action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_message = (
                "You do not have permission to add or remove ping and regex rules."
            )
        elif event.action in {"disable", "enable"}:
            required_permission = ObserverPermission.TOGGLE_PATTERNS
            denial_message = (
                "You do not have permission to enable or disable ping and regex rules."
            )
        else:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_message = (
                "You do not have permission to change ping and regex rules."
            )

        thread = self._ensure_pattern_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=required_permission,
            denial_message=denial_message,
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        if event.action == "add":
            return await self._add_pattern(event, thread)
        if event.action == "remove":
            return await self._remove_pattern(event, thread)
        if event.action == "disable":
            return await self._disable_pattern(event, thread)
        if event.action == "enable":
            return await self._enable_pattern(event, thread)
        raise ValueError("Unsupported action. Use add, remove, disable or enable.")

    def _ensure_pattern_permission(
        self,
        discord_channel_id: int,
        requester_id: int,
        *,
        required_permission: ObserverPermission,
        denial_message: str,
    ) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if not thread_has_permission(
            thread=thread,
            requester_id=requester_id,
            permission_repository=self.permission_repository,
            required_permission=required_permission,
        ):
            return DiscordCommandResult(
                title="Permission Denied",
                message=denial_message,
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread

    async def _add_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Validate and persist a new ping or regex rule."""
        logger.debug("Adding pattern request: %r", event)
        text = (event.pattern_text or "").strip()
        if not text:
            raise ValueError("Please provide a ping or regex pattern.")
        if event.is_regex is None:
            raise ValueError(
                "Please specify whether this pattern should be treated as a regex."
            )
        if event.color is not None and not re.fullmatch(
            r"#[0-9A-Fa-f]{6}",
            event.color.strip(),
        ):
            raise ValueError("Color must use the format `#RRGGBB`.")
        if event.is_regex:
            re.compile(text)

        scoped_channels, scoped_users = await self._resolve_filters(event, thread)

        existing = self.pattern_repository.find_exact_pattern(
            thread_id=thread.thread_id,
            regex=text,
            channel_scope_mode=event.channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=event.user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=event.sub_state,
            offline_state=event.offline_state,
            is_regex=event.is_regex,
            case_sensitive=event.case_sensitive,
        )
        if existing is not None:
            return DiscordCommandResult(
                title="Already Exists",
                message=(
                    f"This {'regex' if event.is_regex else 'ping'} already exists "
                    f"with ID `{existing.p_index}`."
                ),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        created = self.pattern_repository.add_pattern(
            thread_id=thread.thread_id,
            regex=text,
            channel_scope_mode=event.channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=event.user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=event.sub_state,
            offline_state=event.offline_state,
            is_regex=event.is_regex,
            case_sensitive=event.case_sensitive,
            color=event.color.strip() if event.color else None,
            disabled=event.disabled,
            priority=self._default_priority_for(
                channel_scope_mode=event.channel_scope_mode,
                user_scope_mode=event.user_scope_mode,
                sub_state=event.sub_state,
                offline_state=event.offline_state,
            ),
        )
        mode_name = "Regex" if event.is_regex else "Ping"
        logger.debug(
            "Added %s pattern thread_id=%s pattern_id=%s regex=%r channel_filter=%s "
            "user_filter=%s",
            mode_name,
            thread.thread_id,
            created.p_index,
            created.regex,
            created.channel_scope_ids,
            created.user_scope_ids,
        )
        return DiscordCommandResult(
            title=f"{mode_name} Added",
            message=self._format_pattern_summary(
                action="Added",
                pattern=created,
                channel_logins=tuple(channel.login for channel in scoped_channels),
                user_logins=tuple(user.login for user in scoped_users),
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _remove_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Remove a pattern either by ID or by its full identifying fields."""
        logger.debug("Removing pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return DiscordCommandResult(
                title="Not Found",
                message="No matching ping or regex rule was found for removal.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        self.pattern_repository.remove_pattern(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
        )
        logger.debug(
            "Removed pattern thread_id=%s pattern_id=%s regex=%r",
            pattern.thread_id,
            pattern.p_index,
            pattern.regex,
        )
        mode_name = "Regex" if pattern.is_regex else "Ping"
        return DiscordCommandResult(
            title=f"{mode_name} Removed",
            message="\n".join(
                [
                    f"Removed {'regex' if pattern.is_regex else 'ping'} "
                    f"`{pattern.p_index}`.",
                    escape_discord_text(pattern.regex),
                ]
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _disable_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Disable an existing ping or regex rule without deleting it."""
        logger.debug("Disabling pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return DiscordCommandResult(
                title="Not Found",
                message="No matching ping or regex rule was found to disable.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if pattern.disabled:
            return DiscordCommandResult(
                title="Already Disabled",
                message=f"This {'regex' if pattern.is_regex else 'ping'} is already disabled.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
            disabled=True,
        )
        assert updated is not None
        mode_name = "Regex" if pattern.is_regex else "Ping"
        return DiscordCommandResult(
            title=f"{mode_name} Disabled",
            message="\n".join(
                [
                    f"Disabled {'regex' if pattern.is_regex else 'ping'} "
                    f"`{updated.p_index}`.",
                    escape_discord_text(updated.regex),
                ]
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _enable_pattern(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> DiscordCommandResult:
        """Enable an existing ping or regex rule without recreating it."""
        logger.debug("Enabling pattern request: %r", event)
        pattern = await self._locate_pattern_for_removal(event, thread)
        if pattern is None:
            return DiscordCommandResult(
                title="Not Found",
                message="No matching ping or regex rule was found to enable.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not pattern.disabled:
            return DiscordCommandResult(
                title="Already Enabled",
                message=f"This {'regex' if pattern.is_regex else 'ping'} is already enabled.",
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.set_pattern_disabled(
            thread_id=pattern.thread_id,
            p_index=pattern.p_index,
            disabled=False,
        )
        assert updated is not None
        mode_name = "Regex" if pattern.is_regex else "Ping"
        return DiscordCommandResult(
            title=f"{mode_name} Enabled",
            message="\n".join(
                [
                    f"Enabled {'regex' if pattern.is_regex else 'ping'} "
                    f"`{updated.p_index}`.",
                    escape_discord_text(updated.regex),
                ]
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _edit_pattern(
        self,
        event: DiscordPatternEditRequestedEvent,
    ) -> DiscordCommandResult:
        thread = self._ensure_pattern_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_message="You do not have permission to edit ping and regex rules.",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        pattern = self.pattern_repository.get_pattern_by_id(
            thread_id=thread.thread_id,
            p_index=event.pattern_id,
        )
        if pattern is None:
            return DiscordCommandResult(
                title="Not Found",
                message="No ping or regex rule was found for that ID.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        new_text = pattern.regex if event.pattern_text is None else event.pattern_text.strip()
        if not new_text:
            raise ValueError("Please provide a non-empty ping or regex pattern.")

        new_is_regex = pattern.is_regex if event.is_regex is None else event.is_regex
        if new_is_regex:
            re.compile(new_text)

        new_channel_scope_mode = (
            pattern.channel_scope_mode
            if event.channel_scope_mode is None
            else event.channel_scope_mode
        )
        new_user_scope_mode = (
            pattern.user_scope_mode
            if event.user_scope_mode is None
            else event.user_scope_mode
        )
        new_sub_state = pattern.sub_state if event.sub_state is None else event.sub_state
        new_offline_state = (
            pattern.offline_state
            if event.offline_state is None
            else event.offline_state
        )
        new_case_sensitive = (
            pattern.case_sensitive
            if event.case_sensitive is None
            else event.case_sensitive
        )
        if event.clear_color:
            new_color = None
        elif event.color is None:
            new_color = pattern.color
        else:
            new_color = event.color.strip()
        if new_color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", new_color):
            raise ValueError("Color must use the format `#RRGGBB`.")
        new_priority = pattern.priority if event.priority is None else event.priority
        if not 0 <= new_priority <= 9:
            raise ValueError("Priority must be between 0 and 9.")

        scoped_channels, scoped_users = await self._resolve_pattern_edit_filters(
            event,
            thread,
            pattern,
        )

        existing = self.pattern_repository.find_exact_pattern(
            thread_id=thread.thread_id,
            regex=new_text,
            channel_scope_mode=new_channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=new_user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=new_sub_state,
            offline_state=new_offline_state,
            is_regex=new_is_regex,
            case_sensitive=new_case_sensitive,
        )
        if existing is not None and existing.p_index != pattern.p_index:
            return DiscordCommandResult(
                title="Already Exists",
                message=(
                    "Another pattern already uses those exact settings with ID "
                    f"`{existing.p_index}`."
                ),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        updated = self.pattern_repository.update_pattern(
            thread_id=thread.thread_id,
            p_index=pattern.p_index,
            regex=new_text,
            channel_scope_mode=new_channel_scope_mode,
            channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
            user_scope_mode=new_user_scope_mode,
            user_scope_ids=tuple(user.user_id for user in scoped_users),
            sub_state=new_sub_state,
            offline_state=new_offline_state,
            is_regex=new_is_regex,
            case_sensitive=new_case_sensitive,
            color=new_color,
            priority=new_priority,
        )
        assert updated is not None
        old_channel_logins = await self._resolve_channel_logins_from_ids(
            pattern.channel_scope_ids,
        )
        old_user_logins = await self._resolve_user_logins_from_ids(
            pattern.user_scope_ids,
        )
        return DiscordCommandResult(
            title="Pattern Updated",
            message=self._format_pattern_changes(
                before=pattern,
                after=updated,
                old_channel_logins=old_channel_logins,
                new_channel_logins=tuple(channel.login for channel in scoped_channels),
                old_user_logins=old_user_logins,
                new_user_logins=tuple(user.login for user in scoped_users),
            ),
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _resolve_filters(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ):
        """Resolve optional Twitch filters and validate the configured channel scope."""
        if event.channel_scope_mode not in {
            "all_tracked",
            "only_selected",
            "all_except_selected",
        }:
            raise ValueError("Unsupported channel scope.")

        if event.channel_scope_mode == "all_tracked" and event.twitch_channel_logins:
            raise ValueError(
                "Do not provide selected channels when the scope is `all_tracked`."
            )

        if (
            event.channel_scope_mode in {"only_selected", "all_except_selected"}
            and not event.twitch_channel_logins
        ):
            raise ValueError(
                "Please provide at least one tracked channel for this channel scope."
            )

        scoped_channels = []
        for channel_login in event.twitch_channel_logins:
            channel_user = await self.twitch_api.get_user_by_login(channel_login)
            existing_channel = self.channel_repository.get_by_thread_and_twitch_channel(
                thread.thread_id,
                channel_user.user_id,
            )
            if existing_channel is None:
                raise ValueError(
                    f"Twitch channel `{channel_user.login}` is not tracked. "
                    "Add it first with the `/channel` command."
                )
            scoped_channels.append(channel_user)

        if event.user_scope_mode not in {
            "all_users",
            "all_tracked",
            "only_selected",
            "all_except_selected",
            "all_tracked_except_selected",
        }:
            raise ValueError("Unsupported user scope.")

        if event.user_scope_mode in {"all_users", "all_tracked"} and event.twitch_user_logins:
            logger.debug(
                "Ignoring explicitly provided Twitch users because "
                "user_scope_mode=all_users."
            )
            event_user_logins: tuple[str, ...] = ()
        else:
            event_user_logins = event.twitch_user_logins

        if (
            event.user_scope_mode
            in {"only_selected", "all_except_selected", "all_tracked_except_selected"}
            and not event_user_logins
        ):
            raise ValueError("Please provide at least one Twitch user for this user scope.")

        scoped_users = []
        for user_login in event_user_logins:
            resolved_user = await self.twitch_api.get_user_by_login(user_login)
            existing_user = (
                None
                if self.tracked_user_repository is None
                else self.tracked_user_repository.get_by_thread_and_twitch_user(
                    thread.thread_id,
                    resolved_user.user_id,
                )
            )
            if self.tracked_user_repository is not None and existing_user is None:
                raise ValueError(
                    f"Twitch user `{resolved_user.login}` is not tracked in this "
                    "Discord context. Add it first with the `/user` command."
                )
            scoped_users.append(resolved_user)
        return scoped_channels, scoped_users

    async def _resolve_pattern_edit_filters(
        self,
        event: DiscordPatternEditRequestedEvent,
        thread: ThreadRecord,
        pattern: PatternRecord,
    ):
        channel_scope_mode = (
            pattern.channel_scope_mode
            if event.channel_scope_mode is None
            else event.channel_scope_mode
        )
        user_scope_mode = (
            pattern.user_scope_mode
            if event.user_scope_mode is None
            else event.user_scope_mode
        )

        if event.twitch_channel_logins is None:
            if event.channel_scope_mode is None:
                twitch_channel_logins = await self._resolve_channel_logins_from_ids(
                    pattern.channel_scope_ids,
                )
            else:
                twitch_channel_logins = ()
        else:
            twitch_channel_logins = event.twitch_channel_logins

        if event.twitch_user_logins is None:
            if event.user_scope_mode is None:
                twitch_user_logins = await self._resolve_user_logins_from_ids(
                    pattern.user_scope_ids,
                )
            else:
                twitch_user_logins = ()
        else:
            twitch_user_logins = event.twitch_user_logins

        resolved_event = DiscordPatternRequestedEvent(
            discord_channel_id=event.discord_channel_id,
            requester_id=event.requester_id,
            action="add",
            pattern_text=event.pattern_text,
            pattern_id=event.pattern_id,
            is_regex=pattern.is_regex if event.is_regex is None else event.is_regex,
            channel_scope_mode=channel_scope_mode,
            twitch_channel_logins=twitch_channel_logins,
            user_scope_mode=user_scope_mode,
            twitch_user_logins=twitch_user_logins,
            sub_state=pattern.sub_state if event.sub_state is None else event.sub_state,
            offline_state=(
                pattern.offline_state
                if event.offline_state is None
                else event.offline_state
            ),
            case_sensitive=(
                pattern.case_sensitive
                if event.case_sensitive is None
                else event.case_sensitive
            ),
            color=event.color,
            disabled=pattern.disabled,
            result_future=event.result_future,
        )
        return await self._resolve_filters(resolved_event, thread)

    async def _resolve_channel_logins_from_ids(
        self,
        twitch_channel_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        logins: list[str] = []
        for twitch_channel_id in twitch_channel_ids:
            user = await self.twitch_api.get_user_by_id(twitch_channel_id)
            logins.append(user.login)
        return tuple(logins)

    async def _resolve_user_logins_from_ids(
        self,
        twitch_user_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        logins: list[str] = []
        for twitch_user_id in twitch_user_ids:
            user = await self.twitch_api.get_user_by_id(twitch_user_id)
            logins.append(user.login)
        return tuple(logins)

    async def _locate_pattern_for_removal(
        self,
        event: DiscordPatternRequestedEvent,
        thread: ThreadRecord,
    ) -> PatternRecord | None:
        """Locate the exact rule that should be removed."""
        if event.pattern_id is not None:
            return self.pattern_repository.get_pattern_by_id(
                thread_id=thread.thread_id,
                p_index=event.pattern_id,
            )
        raise ValueError(
            "Please provide the stable ID from `/show` to remove a ping or regex rule."
        )

    @staticmethod
    def _format_pattern_summary(
        *,
        action: str,
        pattern: PatternRecord,
        channel_logins: tuple[str, ...],
        user_logins: tuple[str, ...],
    ) -> str:
        parts = [
            f"{action} {'regex' if pattern.is_regex else 'ping'} `{pattern.p_index}`.",
            f"Text: `{pattern.regex}`",
        ]
        channel_scope = PatternCommandService._scope_text(
            mode=pattern.channel_scope_mode,
            selected=channel_logins,
            all_label="Every tracked channel",
            only_label="Only in",
            except_label="Every tracked channel except",
            tracked_except_label="Every tracked channel except",
        )
        user_scope = PatternCommandService._scope_text(
            mode=pattern.user_scope_mode,
            selected=user_logins,
            all_label="All tracked Twitch users",
            only_label="Only from",
            except_label="Everyone except",
            tracked_except_label="All tracked Twitch users except",
        )
        if channel_scope:
            parts.append(channel_scope)
        if user_scope:
            parts.append(user_scope)
        if pattern.sub_state != "all":
            parts.append(
                "Subscribers only"
                if pattern.sub_state == "subs"
                else "Non-subscribers only"
            )
        if pattern.offline_state != "both":
            parts.append(
                "Only while live"
                if pattern.offline_state == "online"
                else "Only while offline"
            )
        parts.append(f"Case-Sensitive: {'`Yes`' if pattern.case_sensitive else '`No`'}")
        if pattern.color:
            parts.append(f"Custom color: `{pattern.color}`")
        parts.append(f"Priority: `{pattern.priority}`")
        return "\n- ".join(parts)

    @staticmethod
    def _format_pattern_changes(
        *,
        before: PatternRecord,
        after: PatternRecord,
        old_channel_logins: tuple[str, ...],
        new_channel_logins: tuple[str, ...],
        old_user_logins: tuple[str, ...],
        new_user_logins: tuple[str, ...],
    ) -> str:
        changes = [f"Updated {'regex' if after.is_regex else 'ping'} `{after.p_index}`."]
        if before.regex != after.regex:
            changes.append(f"Text: From `{before.regex}` to `{after.regex}`")
        if before.is_regex != after.is_regex:
            changes.append(
                "Mode: From "
                f"`{'Regex' if before.is_regex else 'Normal ping'}` to "
                f"`{'Regex' if after.is_regex else 'Normal ping'}`"
            )

        old_channel_scope = PatternCommandService._scope_text(
            mode=before.channel_scope_mode,
            selected=old_channel_logins,
            all_label="Every tracked channel",
            only_label="Only in",
            except_label="Every tracked channel except",
            tracked_except_label="Every tracked channel except",
        )
        new_channel_scope = PatternCommandService._scope_text(
            mode=after.channel_scope_mode,
            selected=new_channel_logins,
            all_label="Every tracked channel",
            only_label="Only in",
            except_label="Every tracked channel except",
            tracked_except_label="Every tracked channel except",
        )
        if old_channel_scope != new_channel_scope:
            changes.append(
                "Where: From "
                f"`{old_channel_scope or 'Every tracked channel'}` to "
                f"`{new_channel_scope or 'Every tracked channel'}`"
            )

        old_user_scope = PatternCommandService._scope_text(
            mode=before.user_scope_mode,
            selected=old_user_logins,
            all_label="All tracked Twitch users",
            only_label="Only from",
            except_label="Everyone except",
            tracked_except_label="All tracked Twitch users except",
        )
        new_user_scope = PatternCommandService._scope_text(
            mode=after.user_scope_mode,
            selected=new_user_logins,
            all_label="All tracked Twitch users",
            only_label="Only from",
            except_label="Everyone except",
            tracked_except_label="All tracked Twitch users except",
        )
        if old_user_scope != new_user_scope:
            changes.append(
                f"Who: From `{old_user_scope or 'Everyone'}` to "
                f"`{new_user_scope or 'Everyone'}`"
            )
        if before.sub_state != after.sub_state:
            changes.append(
                f"Subscribers: From `{before.sub_state}` to `{after.sub_state}`"
            )
        if before.offline_state != after.offline_state:
            changes.append(
                f"Stream state: From `{before.offline_state}` to "
                f"`{after.offline_state}`"
            )
        if before.case_sensitive != after.case_sensitive:
            changes.append(
                "Case-Sensitive: From "
                f"`{'Yes' if before.case_sensitive else 'No'}` to "
                f"`{'Yes' if after.case_sensitive else 'No'}`"
            )
        if before.color != after.color:
            changes.append(
                "Color: From "
                f"`{before.color or 'Inherited automatically'}` to "
                f"`{after.color or 'Inherited automatically'}`"
            )
        if before.priority != after.priority:
            changes.append(
                f"Priority: From `{before.priority}` to `{after.priority}`"
            )
        return "\n- ".join(changes)

    @staticmethod
    def _scope_text(
        *,
        mode: str,
        selected: tuple[str, ...],
        all_label: str,
        only_label: str,
        except_label: str,
        tracked_except_label: str,
    ) -> str | None:
        if mode == "all_users":
            return None
        if mode == "all_tracked":
            return all_label
        if mode == "only_selected":
            return f"{only_label} {', '.join(f'`{item}`' for item in selected)}"
        if mode == "all_except_selected":
            return f"{except_label} {', '.join(f'`{item}`' for item in selected)}"
        if mode == "all_tracked_except_selected":
            return (
                f"{tracked_except_label} "
                f"{', '.join(f'`{item}`' for item in selected)}"
            )
        return None

    @staticmethod
    def _default_priority_for(
        *,
        channel_scope_mode: str,
        user_scope_mode: str,
        sub_state: str,
        offline_state: str,
    ) -> int:
        """Estimate a sensible default priority from rule specificity."""
        priority = 0
        if channel_scope_mode == "only_selected":
            priority += 2
        elif channel_scope_mode == "all_except_selected":
            priority += 1

        if user_scope_mode == "only_selected":
            priority += 4
        elif user_scope_mode == "all_except_selected":
            priority += 2
        elif user_scope_mode == "all_tracked_except_selected":
            priority += 3

        if sub_state != "all":
            priority += 1
        if offline_state != "both":
            priority += 1
        return min(priority, 9)
