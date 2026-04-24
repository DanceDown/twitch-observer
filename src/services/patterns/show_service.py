from __future__ import annotations

"""Business logic for `/show` configuration overviews."""

from dataclasses import dataclass

from src.adapters.twitch_api import TwitchAPIClient
from src.database.connection import (
    AdapterEventActionRecord,
    AdapterEventActionRepository,
    AdapterEventRecord,
    AdapterEventRepository,
    ChannelRepository,
    PatternRecord,
    PatternRepository,
    ReplyRecord,
    ReplyRepository,
    ThreadRecord,
    ThreadRepository,
    TrackedUserRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordResultStyle,
    DiscordShowRequestedEvent,
    EventType,
)
from src.services.authz import thread_has_permission
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.discord_embeds import escape_discord_text
from src.utils.permissions import ObserverPermission, explicit_permission_labels


@dataclass(slots=True)
class ShowCommandService:
    """Build user-facing overviews of stored configuration."""

    event_bus: EventBus
    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    twitch_api: TwitchAPIClient
    tracked_user_repository: TrackedUserRepository | None = None
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
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
                    message="You do not have permission to view the settings.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
                if not event.result_future.done():
                    event.result_future.set_result(result)
                return
            lines = []
            sections = self._normalize_sections(event.sections)
            if "channels" in sections:
                lines.append(await self._render_channels_section(thread.thread_id))
            if "pings" in sections:
                lines.append(await self._render_patterns_section(thread.thread_id, title="Pings"))
            if "auto_replies" in sections:
                lines.append(await self._render_auto_replies_section(thread.thread_id))
            if "users" in sections:
                lines.append(await self._render_users_section(thread.thread_id))
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

        allowed = {"channels", "pings", "auto_replies", "users", "permissions"}
        normalized = tuple(section for section in raw_sections if section in allowed)
        if normalized:
            return normalized
        return ("channels",)

    async def _render_channels_section(self, thread_id: int) -> str:
        """Render the tracked Twitch channels for one Discord configuration root."""
        channels = self.channel_repository.list_channels_for_thread(thread_id)
        if not channels:
            return "**Tracked Channels**\nNo Twitch channels are connected yet."

        rows: list[str] = []
        thread_events = (
            []
            if self.adapter_event_repository is None
            else self.adapter_event_repository.list_events_for_thread(
                thread_id,
                include_disabled=False,
            )
        )
        event_state_by_channel_id = {
            event.subject_id: sorted(
                STREAM_EVENT_KEY_TO_STATE[item.event_key]
                for item in thread_events
                if item.adapter_key == TWITCH_ADAPTER_KEY
                and item.subject_type == CHANNEL_SUBJECT_TYPE
                and item.subject_id == event.subject_id
                and item.event_key in STREAM_EVENT_KEY_TO_STATE
            )
            for event in thread_events
            if event.adapter_key == TWITCH_ADAPTER_KEY
            and event.subject_type == CHANNEL_SUBJECT_TYPE
        }
        for channel in channels:
            twitch_user = await self.twitch_api.get_user_by_id(channel.twitch_channel_id)
            line = (
                f"- [{escape_discord_text(twitch_user.display_name)}]"
                f"(https://www.twitch.tv/{twitch_user.login})"
            )
            if channel.color:
                line += f"\n  Custom color: `{channel.color}`"
            if channel.is_live is not None:
                line += f"\n  Live state: `{'online' if channel.is_live else 'offline'}`"
            configured_states = event_state_by_channel_id.get(channel.twitch_channel_id, [])
            if configured_states:
                line += f"\n  Notifications: `{', '.join(configured_states)}`"
            rows.append(line)
        return "**Tracked Channels**\n" + "\n".join(rows)

    async def _render_patterns_section(self, thread_id: int, *, title: str) -> str:
        """Render all stored ping and regex rules with stable IDs for removals."""
        patterns = self.pattern_repository.list_patterns_for_thread(
            thread_id,
            is_regex=None,
        )
        if not patterns:
            return f"**{title}**\nNo pings are saved yet."
        rows = [await self._format_pattern_row(pattern) for pattern in patterns]
        return f"**{title}**\n" + "\n".join(rows)

    async def _render_auto_replies_section(self, thread_id: int) -> str:
        """Render all patterns that currently have an attached reply."""
        replies = self.reply_repository.list_replies_for_thread(
            thread_id,
            include_disabled=True,
        )
        adapter_event_actions = (
            []
            if self.adapter_event_action_repository is None
            or self.adapter_event_repository is None
            else [
                (event_record, action_record)
                for event_record, action_record in (
                    self.adapter_event_action_repository.list_actions_for_thread(
                        thread_id,
                        include_disabled=True,
                    )
                )
                if action_record.action_type == TWITCH_SEND_MESSAGE_ACTION
            ]
        )
        if not replies and not adapter_event_actions:
            return "**Auto-Replies**\nThere are no automatic replies configured."
        rows: list[str] = []
        for reply in replies:
            pattern = self.pattern_repository.get_pattern_by_id(
                thread_id=thread_id,
                p_index=reply.p_index,
            )
            if pattern is None:
                continue
            rows.append(await self._format_auto_reply_row(pattern, reply))
        for adapter_event, action in adapter_event_actions:
            rows.append(await self._format_adapter_event_action_row(adapter_event, action))
        if not rows:
            return "**Auto-Replies**\nThere are no automatic replies configured."
        return "**Auto-Replies**\n" + "\n".join(rows)

    async def _render_users_section(self, thread_id: int) -> str:
        """Render the tracked Twitch users for one Discord configuration root."""
        if self.tracked_user_repository is None:
            return "**Tracked Users**\nThere are no Twitch users are connected yet."
        tracked_users = self.tracked_user_repository.list_users_for_thread(thread_id)
        if not tracked_users:
            return "**Tracked Users**\nThere are no Twitch users are connected yet."
        rows: list[str] = []
        for tracked_user in tracked_users:
            twitch_user = await self.twitch_api.get_user_by_id(tracked_user.twitch_user_id)
            rows.append(
                f"- [{escape_discord_text(twitch_user.display_name)}]"
                f"(https://www.twitch.tv/{twitch_user.login})"
            )
        return "**Tracked Users**\n" + "\n".join(rows)

    def _render_permissions_section(self, thread: ThreadRecord) -> str:
        rows = [f"- <@{thread.owner_id}>\n  `Owner (all permissions)`"]
        if self.permission_repository is None:
            return "**Permissions**\n" + "\n".join(rows)
        grants = self.permission_repository.list_for_thread(thread_id=thread.thread_id)
        for grant in grants:
            labels = explicit_permission_labels(grant.permissions)
            rendered = (
                "\n".join(f"  - {self._permission_label(label)}" for label in labels)
                if labels
                else "  - No extra permissions"
            )
            rows.append(f"- <@{grant.discord_user_id}>\n{rendered}")
        return "**Permissions**\n" + "\n".join(rows)

    async def _format_pattern_row(self, pattern: PatternRecord) -> str:
        """Render one compact row containing all identifying pattern fields."""
        parts = [
            f"- {'Regex' if pattern.is_regex else 'Ping'} `{pattern.p_index}`",
            f"  Text: `{pattern.regex}`",
        ]
        details = await self._describe_pattern_details(pattern)
        parts.extend(f"  {detail}" for detail in details)
        return "\n".join(parts)

    async def _format_auto_reply_row(
        self,
        pattern: PatternRecord,
        reply: ReplyRecord,
    ) -> str:
        """Render one compact row for an attached auto-reply."""
        details = [f"- `{pattern.p_index}`"]
        trigger = self._format_show_code_unescaped(pattern.regex)
        response = self._format_show_code_unescaped(reply.reply_message)
        details.append(f"  Trigger: `{trigger}`")
        details.append(f"  Reply: `{response}`")
        return "\n".join(details)

    async def _format_adapter_event_action_row(
        self,
        event: AdapterEventRecord,
        action: AdapterEventActionRecord,
    ) -> str:
        channel_user = await self.twitch_api.get_user_by_id(event.subject_id)
        response = self._format_show_code_unescaped(action.message_template or "")
        state_label = STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key)
        details = [f"- Event `{state_label}`"]
        details.append(
            f"  Channel: [{escape_discord_text(channel_user.display_name)}]"
            f"(https://www.twitch.tv/{channel_user.login})"
        )
        details.append(f"  Reply: `{response}`")
        if action.disabled:
            details.append("  Disabled")
        return "\n".join(details)

    async def _describe_pattern_details(self, pattern: PatternRecord) -> list[str]:
        details: list[str] = []
        if pattern.channel_scope_mode != "all_tracked":
            channel_names = await self._resolve_twitch_links(pattern.channel_scope_ids)
            if pattern.channel_scope_mode == "only_selected":
                details.append(f"Only in {', '.join(channel_names)}")
            elif pattern.channel_scope_mode == "all_except_selected":
                details.append(
                    f"Every tracked channel except {', '.join(channel_names)}"
                )
        if pattern.user_scope_mode != "all_users":
            user_names = await self._resolve_twitch_names(pattern.user_scope_ids)
            if pattern.user_scope_mode == "only_selected":
                details.append(f"Only from {', '.join(user_names)}")
            elif pattern.user_scope_mode == "all_except_selected":
                details.append(f"Everyone except {', '.join(user_names)}")
            elif pattern.user_scope_mode == "all_tracked":
                details.append("Only from tracked Twitch users")
            elif pattern.user_scope_mode == "all_tracked_except_selected":
                details.append(
                    "Only from tracked Twitch users except "
                    f"{', '.join(user_names)}"
                )
        if pattern.sub_state != "all":
            details.append(
                "Subscribers only"
                if pattern.sub_state == "subs"
                else "Non-subscribers only"
            )
        if pattern.offline_state != "both":
            details.append(
                "Only while live"
                if pattern.offline_state == "online"
                else "Only while offline"
            )
        if pattern.case_sensitive:
            details.append("Case Sensitive")
        if pattern.color:
            details.append(f"Custom color: `{pattern.color}`")
        details.append(f"Priority: `{pattern.priority}`")
        if pattern.disabled:
            details.append("Disabled")
        return details

    async def _resolve_twitch_links(
        self,
        twitch_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self.twitch_api.get_user_by_id(twitch_id)
            resolved.append(
                f"[{escape_discord_text(user.display_name)}]"
                f"(https://www.twitch.tv/{user.login})"
            )
        return tuple(resolved)

    async def _resolve_twitch_names(
        self,
        twitch_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self.twitch_api.get_user_by_id(twitch_id)
            resolved.append(
                f"[{escape_discord_text(user.display_name)}]"
                f"(https://www.twitch.tv/{user.login})"
            )
        return tuple(resolved)

    @staticmethod
    def _permission_label(label: str) -> str:
        return {
            "view": "View configuration",
            "manage_channels": "Add and remove channels",
            "toggle_patterns": "Enable and disable pings",
            "manage_patterns": "Create, edit and remove pings",
            "toggle_replies": "Enable and disable auto-replies",
            "manage_replies": "Create and remove auto-replies",
            "send_twitch_messages": "Send Twitch messages",
            "control_observer": "Turn the observer on or off",
            "leave_context": "Disconnect this Discord channel",
            "manage_permissions": "Manage permissions",
            "admin": "Administrator",
        }.get(label, label.replace("_", " ").capitalize())

    @staticmethod
    def _format_show_code_unescaped(text: str) -> str:
        if "`" in text:
            return text
        return f"`{text}`"
