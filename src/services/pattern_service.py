from __future__ import annotations

"""Business logic for `/ping` commands, live tracking and show output."""

import re
from dataclasses import dataclass
import logging

import discord

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
    ReplyRecord,
    ReplyRepository,
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
    DiscordShowRequestedEvent,
    EventType,
    TwitchChatMessageEvent,
)
from src.services.authz import thread_has_permission
from src.utils.discord_embeds import build_tracking_embed
from src.utils.permissions import ObserverPermission, explicit_permission_labels
from src.utils.pattern_matching import matches_pattern

logger = logging.getLogger(__name__)


class TrackingNotificationSender:
    """Interface used by the tracking service to emit Discord embeds."""

    async def send_tracking_embed(self, discord_channel_id: int, embed: discord.Embed) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass(slots=True)
class PatternCommandService:
    """Handle `/ping` add/edit/remove requests from Discord."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        """Subscribe the service to incoming Discord pattern command events."""
        self.event_bus.subscribe(EventType.DISCORD_PATTERN_REQUESTED, self.handle_request)
        self.event_bus.subscribe(EventType.DISCORD_PATTERN_EDIT_REQUESTED, self.handle_edit_request)

    async def handle_request(self, event: DiscordPatternRequestedEvent) -> None:
        """Handle one add/remove request and complete the command result future."""
        try:
            result = await self._handle_action(event)
        except (TwitchAPIConfigurationError, TwitchChannelNotFoundError, ValueError) as error:
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
        except (TwitchAPIConfigurationError, TwitchChannelNotFoundError, ValueError) as error:
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

    async def _handle_action(self, event: DiscordPatternRequestedEvent) -> DiscordCommandResult:
        if event.action in {"add", "remove"}:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_message = "You do not have permission to add or remove ping and regex rules in this Discord channel."
        elif event.action in {"disable", "enable"}:
            required_permission = ObserverPermission.TOGGLE_PATTERNS
            denial_message = "You do not have permission to enable or disable ping and regex rules in this Discord channel."
        else:
            required_permission = ObserverPermission.MANAGE_PATTERNS
            denial_message = "You do not have permission to change ping and regex rules in this Discord channel."

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

    async def _add_pattern(self, event: DiscordPatternRequestedEvent, thread: ThreadRecord) -> DiscordCommandResult:
        """Validate and persist a new ping or regex rule."""
        logger.debug("Adding pattern request: %r", event)
        text = (event.pattern_text or "").strip()
        if not text:
            raise ValueError("Please provide a ping or regex pattern.")
        if event.is_regex is None:
            raise ValueError("Please specify whether this rule should be treated as a regex.")
        if event.color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", event.color.strip()):
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
                message=f"This {'regex' if event.is_regex else 'ping'} already exists with ID `{existing.p_index}`.",
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
                channel_scope_ids=tuple(channel.user_id for channel in scoped_channels),
                user_scope_mode=event.user_scope_mode,
                user_scope_ids=tuple(user.user_id for user in scoped_users),
                sub_state=event.sub_state,
                offline_state=event.offline_state,
            ),
        )
        mode_name = "Regex" if event.is_regex else "Ping"
        logger.debug(
            "Added %s pattern thread_id=%s pattern_id=%s regex=%r channel_filter=%s user_filter=%s",
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

    async def _remove_pattern(self, event: DiscordPatternRequestedEvent, thread: ThreadRecord) -> DiscordCommandResult:
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
        logger.debug("Removed pattern thread_id=%s pattern_id=%s regex=%r", pattern.thread_id, pattern.p_index, pattern.regex)
        mode_name = "Regex" if pattern.is_regex else "Ping"
        return DiscordCommandResult(
            title=f"{mode_name} Removed",
            message=f"Removed {'regex' if pattern.is_regex else 'ping'} with ID `{pattern.p_index}`: `{pattern.regex}`.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _disable_pattern(self, event: DiscordPatternRequestedEvent, thread: ThreadRecord) -> DiscordCommandResult:
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
            message=f"Disabled {'regex' if pattern.is_regex else 'ping'} with ID `{updated.p_index}`: `{updated.regex}`.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _enable_pattern(self, event: DiscordPatternRequestedEvent, thread: ThreadRecord) -> DiscordCommandResult:
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
            message=f"Enabled {'regex' if pattern.is_regex else 'ping'} with ID `{updated.p_index}`: `{updated.regex}`.",
            style=DiscordResultStyle.SUCCESS,
            ephemeral=False,
        )

    async def _edit_pattern(self, event: DiscordPatternEditRequestedEvent) -> DiscordCommandResult:
        thread = self._ensure_pattern_permission(
            event.discord_channel_id,
            event.requester_id,
            required_permission=ObserverPermission.MANAGE_PATTERNS,
            denial_message="You do not have permission to edit ping and regex rules in this Discord channel.",
        )
        if isinstance(thread, DiscordCommandResult):
            return thread

        pattern = self.pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, p_index=event.pattern_id)
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

        new_channel_scope_mode = pattern.channel_scope_mode if event.channel_scope_mode is None else event.channel_scope_mode
        new_user_scope_mode = pattern.user_scope_mode if event.user_scope_mode is None else event.user_scope_mode
        new_sub_state = pattern.sub_state if event.sub_state is None else event.sub_state
        new_offline_state = pattern.offline_state if event.offline_state is None else event.offline_state
        new_case_sensitive = pattern.case_sensitive if event.case_sensitive is None else event.case_sensitive
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

        scoped_channels, scoped_users = await self._resolve_pattern_edit_filters(event, thread, pattern)

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
                message=f"Another pattern already uses those exact settings with ID `{existing.p_index}`.",
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
        return DiscordCommandResult(
            title="Pattern Updated",
            message=self._format_pattern_summary(
                action="Updated",
                pattern=updated,
                channel_logins=tuple(channel.login for channel in scoped_channels),
                user_logins=tuple(user.login for user in scoped_users),
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
        if event.channel_scope_mode not in {"all_tracked", "only_selected", "all_except_selected"}:
            raise ValueError("Unsupported channel scope.")

        if event.channel_scope_mode == "all_tracked" and event.twitch_channel_logins:
            raise ValueError("Do not provide selected channels when the scope is `all_tracked`.")

        if event.channel_scope_mode in {"only_selected", "all_except_selected"} and not event.twitch_channel_logins:
            raise ValueError("Please provide at least one tracked channel for this channel scope.")

        scoped_channels = []
        for channel_login in event.twitch_channel_logins:
            channel_user = await self.twitch_api.get_user_by_login(channel_login)
            existing_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, channel_user.user_id)
            if existing_channel is None:
                raise ValueError(
                    f"Twitch channel `{channel_user.login}` is not tracked in this Discord context. "
                    "Add it first with `/channel add`."
                )
            scoped_channels.append(channel_user)

        if event.user_scope_mode not in {"all_users", "only_selected", "all_except_selected"}:
            raise ValueError("Unsupported user scope.")

        if event.user_scope_mode == "all_users" and event.twitch_user_logins:
            raise ValueError("Do not provide selected users when the scope is `all_users`.")

        if event.user_scope_mode in {"only_selected", "all_except_selected"} and not event.twitch_user_logins:
            raise ValueError("Please provide at least one Twitch user for this user scope.")

        scoped_users = []
        for user_login in event.twitch_user_logins:
            scoped_users.append(await self.twitch_api.get_user_by_login(user_login))
        return scoped_channels, scoped_users

    async def _resolve_pattern_edit_filters(
        self,
        event: DiscordPatternEditRequestedEvent,
        thread: ThreadRecord,
        pattern: PatternRecord,
    ):
        channel_scope_mode = pattern.channel_scope_mode if event.channel_scope_mode is None else event.channel_scope_mode
        user_scope_mode = pattern.user_scope_mode if event.user_scope_mode is None else event.user_scope_mode

        if event.twitch_channel_logins is None:
            if event.channel_scope_mode is None:
                twitch_channel_logins = await self._resolve_channel_logins_from_ids(pattern.channel_scope_ids)
            else:
                twitch_channel_logins = ()
        else:
            twitch_channel_logins = event.twitch_channel_logins

        if event.twitch_user_logins is None:
            if event.user_scope_mode is None:
                twitch_user_logins = await self._resolve_user_logins_from_ids(pattern.user_scope_ids)
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
            offline_state=pattern.offline_state if event.offline_state is None else event.offline_state,
            case_sensitive=pattern.case_sensitive if event.case_sensitive is None else event.case_sensitive,
            color=event.color,
            disabled=pattern.disabled,
            result_future=event.result_future,
        )
        return await self._resolve_filters(resolved_event, thread)

    async def _resolve_channel_logins_from_ids(self, twitch_channel_ids: tuple[str, ...]) -> tuple[str, ...]:
        logins: list[str] = []
        for twitch_channel_id in twitch_channel_ids:
            user = await self.twitch_api.get_user_by_id(twitch_channel_id)
            logins.append(user.login)
        return tuple(logins)

    async def _resolve_user_logins_from_ids(self, twitch_user_ids: tuple[str, ...]) -> tuple[str, ...]:
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
        raise ValueError("Please provide the stable ID from `/show` to remove a ping or regex rule.")

    @staticmethod
    def _format_pattern_summary(
        *,
        action: str,
        pattern: PatternRecord,
        channel_logins: tuple[str, ...],
        user_logins: tuple[str, ...],
    ) -> str:
        parts = [f"{action} pattern with ID `{pattern.p_index}`: `{pattern.regex}`."]
        parts.append(f"Channel scope: `{pattern.channel_scope_mode}`.")
        if channel_logins:
            parts.append(f"Scoped channels: `{', '.join(channel_logins)}`.")
        parts.append(f"User scope: `{pattern.user_scope_mode}`.")
        if user_logins:
            parts.append(f"Scoped users: `{', '.join(user_logins)}`.")
        parts.append(f"Sub-state: `{pattern.sub_state}`.")
        parts.append(f"Offline-state: `{pattern.offline_state}`.")
        parts.append(f"Priority: `{pattern.priority}`.")
        return " ".join(parts)

    @staticmethod
    def _default_priority_for(
        *,
        channel_scope_mode: str,
        channel_scope_ids: tuple[str, ...],
        user_scope_mode: str,
        user_scope_ids: tuple[str, ...],
        sub_state: str,
        offline_state: str,
    ) -> int:
        """Estimate a sensible default priority from rule specificity."""
        priority = 0
        if channel_scope_mode == "only_selected":
            priority += 2 if channel_scope_ids else 0
        elif channel_scope_mode == "all_except_selected":
            priority += 1

        if user_scope_mode == "only_selected":
            priority += 4 if user_scope_ids else 0
        elif user_scope_mode == "all_except_selected":
            priority += 2

        if sub_state != "all":
            priority += 1
        if offline_state != "both":
            priority += 1
        return min(priority, 9)


@dataclass(slots=True)
class ShowCommandService:
    """Build user-facing overviews of stored configuration."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    permission_repository: UserPermissionRepository | None = None

    def __post_init__(self) -> None:
        """Subscribe the service to `/show` requests."""
        self.event_bus.subscribe(EventType.DISCORD_SHOW_REQUESTED, self.handle_show_request)

    async def handle_show_request(self, event: DiscordShowRequestedEvent) -> None:
        """Create an overview embed body for the selected sections."""
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            result = DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        else:
            if not thread_has_permission(
                thread=thread,
                requester_id=event.requester_id,
                permission_repository=self.permission_repository,
                required_permission=ObserverPermission.VIEW,
            ):
                result = DiscordCommandResult(
                    title="Permission Denied",
                    message="You do not have permission to view this Discord channel configuration.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
                if not event.result_future.done():
                    event.result_future.set_result(result)
                return
            lines = []
            sections = self._normalize_sections(event.sections)
            if "channels" in sections:
                lines.append(self._render_channels_section(thread.thread_id))
            if "pings" in sections:
                lines.append(self._render_patterns_section(thread.thread_id, title="Pings"))
            if "auto_replies" in sections:
                lines.append(self._render_auto_replies_section(thread.thread_id))
            if "permissions" in sections:
                lines.append(self._render_permissions_section(thread))
            result = DiscordCommandResult(
                title="Configuration Overview",
                message="\n\n".join(section for section in lines if section),
                style=DiscordResultStyle.INFO,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    @staticmethod
    def _normalize_sections(raw_sections: tuple[str, ...]) -> tuple[str, ...]:
        """Validate the requested show sections against the supported set."""
        if not raw_sections:
            return ("channels",)

        allowed = {"channels", "pings", "auto_replies", "permissions"}
        normalized = tuple(section for section in raw_sections if section in allowed)
        if normalized:
            return normalized
        return ("channels",)

    def _render_channels_section(self, thread_id: int) -> str:
        """Render the tracked Twitch channels for one Discord configuration root."""
        channels = self.channel_repository.list_channels_for_thread(thread_id)
        if not channels:
            return "**Channels**\n`None`"
        rows = [f"- twitch_channel_id=`{channel.twitch_channel_id}`" for channel in channels]
        return "**Channels**\n" + "\n".join(rows)

    def _render_patterns_section(self, thread_id: int, *, title: str) -> str:
        """Render all stored ping and regex rules with stable IDs for removals."""
        patterns = self.pattern_repository.list_patterns_for_thread(thread_id, is_regex=None)
        if not patterns:
            return f"**{title}**\n`None`"
        rows = [self._format_pattern_row(pattern) for pattern in patterns]
        return f"**{title}**\n" + "\n".join(rows)

    def _render_auto_replies_section(self, thread_id: int) -> str:
        """Render all patterns that currently have an attached reply."""
        replies = self.reply_repository.list_replies_for_thread(thread_id, include_disabled=True)
        if not replies:
            return "**Auto-Replies**\n`None`"
        rows: list[str] = []
        for reply in replies:
            pattern = self.pattern_repository.get_pattern_by_id(thread_id=thread_id, p_index=reply.p_index)
            if pattern is None:
                continue
            rows.append(self._format_auto_reply_row(pattern, reply))
        if not rows:
            return "**Auto-Replies**\n`None`"
        return "**Auto-Replies**\n" + "\n".join(rows)

    def _render_permissions_section(self, thread: ThreadRecord) -> str:
        rows = [f"- owner=`{thread.owner_id}` (all permissions)"]
        if self.permission_repository is None:
            return "**Permissions**\n" + "\n".join(rows)
        grants = self.permission_repository.list_for_thread(thread_id=thread.thread_id)
        for grant in grants:
            labels = explicit_permission_labels(grant.permissions)
            rendered = ", ".join(f"`{label}`" for label in labels) if labels else "`none`"
            rows.append(f"- user=`{grant.discord_user_id}`, permissions={rendered}")
        return "**Permissions**\n" + "\n".join(rows)

    @staticmethod
    def _format_pattern_row(pattern: PatternRecord) -> str:
        """Render one compact row containing all identifying pattern fields."""
        extras = [
            f"id=`{pattern.p_index}`",
            f"priority=`{pattern.priority}`",
            f"type=`{'regex' if pattern.is_regex else 'ping'}`",
            f"text=`{pattern.regex}`",
        ]
        extras.append(f"scope=`{pattern.channel_scope_mode}`")
        if pattern.channel_scope_ids:
            extras.append(f"channels=`{','.join(pattern.channel_scope_ids)}`")
        extras.append(f"user_scope=`{pattern.user_scope_mode}`")
        if pattern.user_scope_ids:
            extras.append(f"users=`{','.join(pattern.user_scope_ids)}`")
        extras.append(f"sub=`{pattern.sub_state}`")
        extras.append(f"offline=`{pattern.offline_state}`")
        if pattern.color:
            extras.append(f"color=`{pattern.color}`")
        if pattern.case_sensitive:
            extras.append("case=`true`")
        if pattern.disabled:
            extras.append("disabled=`true`")
        return "- " + ", ".join(extras)

    @staticmethod
    def _format_auto_reply_row(pattern: PatternRecord, reply: ReplyRecord) -> str:
        """Render one compact row for an attached auto-reply."""
        mode = "reply" if reply.reply_as_reply else "message"
        return (
            f"- pattern_id=`{pattern.p_index}`, "
            f"type=`{'regex' if pattern.is_regex else 'ping'}`, "
            f"mode=`{mode}`, "
            f"disabled=`{'true' if reply.disabled else 'false'}`, "
            f"match=`{pattern.regex}`, "
            f"message=`{reply.reply_message}`"
        )


@dataclass(slots=True)
class PatternTrackingService:
    """Evaluate incoming Twitch messages against stored ping/regex definitions."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    twitch_api: TwitchAPIClient
    notifier: TrackingNotificationSender
    reply_repository: ReplyRepository | None = None

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.TWITCH_CHAT_MESSAGE, self.handle_chat_message)

    async def handle_chat_message(self, event: TwitchChatMessageEvent) -> None:
        """Check all interested Discord channels for pattern matches."""
        logger.debug(
            "Evaluating incoming Twitch message channel=%s broadcaster_id=%s author=%s author_id=%s content=%r",
            event.channel_login,
            event.broadcaster_id,
            event.author_login,
            event.author_id,
            event.content,
        )
        if not event.broadcaster_id:
            logger.debug("Skipping Twitch message because broadcaster_id is missing.")
            return

        thread_ids = self.channel_repository.list_thread_ids_by_twitch_channel_id(event.broadcaster_id)
        if not thread_ids:
            logger.debug("No Discord threads track broadcaster_id=%s", event.broadcaster_id)
            return

        live_status: bool | None = None
        for thread_id in thread_ids:
            thread = self.thread_repository.get_by_thread_id(thread_id)
            if thread is None:
                logger.debug("Skipping missing thread_id=%s referenced by channel repository.", thread_id)
                continue
            if not thread.enabled:
                logger.debug("Skipping disabled thread_id=%s during tracking evaluation.", thread.thread_id)
                continue

            patterns = self.pattern_repository.list_active_patterns_for_thread(thread.thread_id)
            logger.debug("Thread %s has %d active pattern(s).", thread.thread_id, len(patterns))
            source_channel = self.channel_repository.get_by_thread_and_twitch_channel(thread.thread_id, event.broadcaster_id)
            for pattern in patterns:
                if not matches_pattern(pattern, event):
                    logger.debug(
                        "Pattern %s did not match message. regex=%r channel_filter=%s user_filter=%s sub=%s offline=%s is_regex=%s",
                        pattern.p_index,
                        pattern.regex,
                        pattern.channel_scope_ids,
                        pattern.user_scope_ids,
                        pattern.sub_state,
                        pattern.offline_state,
                        pattern.is_regex,
                    )
                    continue
                if pattern.offline_state != "both" and live_status is None:
                    live_status = await self.twitch_api.is_user_live(event.broadcaster_id)
                if not self._offline_state_allows(pattern, live_status):
                    logger.debug(
                        "Pattern %s matched text but was filtered by offline_state=%s live_status=%s",
                        pattern.p_index,
                        pattern.offline_state,
                        live_status,
                    )
                    continue

                if self._has_enabled_reply(thread.thread_id, pattern.p_index):
                    logger.debug(
                        "Pattern %s matched for thread_id=%s but notification is delegated to auto-reply handling.",
                        pattern.p_index,
                        thread.thread_id,
                    )
                    break

                logger.debug("Pattern %s matched. Sending tracking embed to discord_channel_id=%s", pattern.p_index, thread.discord_channel_id)
                await self.notifier.send_tracking_embed(
                    thread.discord_channel_id,
                    build_tracking_embed(event=event, pattern=pattern, thread=thread, channel=source_channel),
                )
                break

    @staticmethod
    def _offline_state_allows(pattern: PatternRecord, live_status: bool | None) -> bool:
        if pattern.offline_state == "both" or live_status is None:
            return True
        if pattern.offline_state == "online":
            return live_status
        if pattern.offline_state == "offline":
            return not live_status
        return False

    def _has_enabled_reply(self, thread_id: int, pattern_id: int) -> bool:
        if self.reply_repository is None:
            return False
        reply = self.reply_repository.get_by_pattern(thread_id=thread_id, p_index=pattern_id)
        return reply is not None and not reply.disabled
