"""Business logic for `/show` configuration overviews."""

from __future__ import annotations

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
    TwitchAccountRepository,
    TwitchDeviceFlowRepository,
    UserPermissionRepository,
)
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordResultStyle,
    DiscordShowRequestedEvent,
    EventType,
)
from src.localization import Localizer
from src.services.authz import thread_has_permission
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.discord_embeds import format_twitch_code_link
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
    localizer: Localizer | None = None
    permission_repository: UserPermissionRepository | None = None
    account_repository: TwitchAccountRepository | None = None
    device_flow_repository: TwitchDeviceFlowRepository | None = None

    def __post_init__(self) -> None:
        """Subscribe the service to `/show` requests."""
        self.event_bus.subscribe(EventType.DISCORD_SHOW_REQUESTED, self.handle_show_request)

    async def handle_show_request(self, event: DiscordShowRequestedEvent) -> None:
        """Create an overview embed body for the selected sections."""
        thread = self.thread_repository.get_by_discord_channel_id(event.discord_channel_id)
        if thread is None:
            result = self._localizer.result(
                "results.not_joined",
                language=self._localizer.default_language,
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
                result = self._localizer.thread_result(
                    "results.show.permission_denied",
                    thread=thread,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
                if not event.result_future.done():
                    event.result_future.set_result(result)
                return
            lines = []
            sections = self._normalize_sections(event.sections)
            language = self._localizer.language_for_thread(thread)
            if "channels" in sections:
                lines.append(await self._render_channels_section(thread.thread_id))
            if "pings" in sections:
                lines.append(
                    await self._render_patterns_section(
                        thread.thread_id,
                        title=self._localizer.text("show.sections.pings", language=language),
                    )
                )
            if "auto_replies" in sections:
                lines.append(await self._render_auto_replies_section(thread.thread_id))
            if "users" in sections:
                lines.append(await self._render_users_section(thread.thread_id))
            if "permissions" in sections:
                lines.append(self._render_permissions_section(thread))
            thumbnail_url = None
            if "account" in sections:
                account_section, thumbnail_url = await self._render_account_section(thread)
                lines.append(account_section)
            result = self._localizer.thread_result(
                "results.show.overview",
                thread=thread,
                style=DiscordResultStyle.INFO,
                ephemeral=True,
                CONTENT="\n\n".join(section for section in lines if section),
                thumbnail_url=thumbnail_url,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    @staticmethod
    def _normalize_sections(raw_sections: tuple[str, ...]) -> tuple[str, ...]:
        """Validate the requested show sections against the supported set."""
        if not raw_sections:
            return ("channels",)

        allowed = {"channels", "pings", "auto_replies", "users", "permissions", "account"}
        normalized = tuple(section for section in raw_sections if section in allowed)
        if normalized:
            return normalized
        return ("channels",)

    async def _render_channels_section(self, thread_id: int) -> str:
        """Render the tracked Twitch channels for one Discord configuration root."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        channels = self.channel_repository.list_channels_for_thread(thread_id)
        if not channels:
            return (
                f"**{self._localizer.text('show.sections.tracked_channels', language=language)}**\n"
                f"{self._localizer.text('show.empty.tracked_channels', language=language)}"
            )

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
            if event.adapter_key == TWITCH_ADAPTER_KEY and event.subject_type == CHANNEL_SUBJECT_TYPE
        }
        for channel in channels:
            twitch_user = await self._resolve_channel_by_id(channel.twitch_channel_id)
            line = f"- {format_twitch_code_link(display_name=twitch_user.display_name, login=twitch_user.login)}"
            if channel.color:
                line += "\n  " + self._localizer.text(
                    "show.channel.custom_color",
                    language=language,
                    COLOR=channel.color,
                )
            if channel.is_live is not None:
                line += "\n  " + self._localizer.text(
                    "show.channel.live_state",
                    language=language,
                    STATE="online" if channel.is_live else "offline",
                )
            configured_states = event_state_by_channel_id.get(channel.twitch_channel_id, [])
            if configured_states:
                line += "\n  " + self._localizer.text(
                    "show.channel.notifications",
                    language=language,
                    STATES=", ".join(configured_states),
                )
            rows.append(line)
        return f"**{self._localizer.text('show.sections.tracked_channels', language=language)}**\n" + "\n".join(rows)

    async def _render_patterns_section(self, thread_id: int, *, title: str) -> str:
        """Render all stored ping and regex rules with stable IDs for removals."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        patterns = self.pattern_repository.list_patterns_for_thread(
            thread_id,
            is_regex=None,
        )
        if not patterns:
            return f"**{title}**\n{self._localizer.text('show.empty.pings', language=language)}"
        rows = [await self._format_pattern_row(pattern, language=language) for pattern in patterns]
        return f"**{title}**\n" + "\n".join(rows)

    async def _render_auto_replies_section(self, thread_id: int) -> str:
        """Render all patterns that currently have an attached reply."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        replies = self.reply_repository.list_replies_for_thread(
            thread_id,
            include_disabled=True,
        )
        adapter_event_actions = (
            []
            if self.adapter_event_action_repository is None or self.adapter_event_repository is None
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
            return (
                f"**{self._localizer.text('show.sections.auto_replies', language=language)}**\n"
                f"{self._localizer.text('show.empty.auto_replies', language=language)}"
            )
        rows: list[str] = []
        for reply in replies:
            pattern = self.pattern_repository.get_pattern_by_id(
                thread_id=thread_id,
                p_index=reply.p_index,
            )
            if pattern is None:
                continue
            rows.append(await self._format_auto_reply_row(pattern, reply, language=language))
        for adapter_event, action in adapter_event_actions:
            rows.append(await self._format_adapter_event_action_row(adapter_event, action, language=language))
        if not rows:
            return (
                f"**{self._localizer.text('show.sections.auto_replies', language=language)}**\n"
                f"{self._localizer.text('show.empty.auto_replies', language=language)}"
            )
        return f"**{self._localizer.text('show.sections.auto_replies', language=language)}**\n" + "\n".join(rows)

    async def _render_users_section(self, thread_id: int) -> str:
        """Render the tracked Twitch users for one Discord configuration root."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        if self.tracked_user_repository is None:
            return (
                f"**{self._localizer.text('show.sections.tracked_users', language=language)}**\n"
                f"{self._localizer.text('show.empty.tracked_users', language=language)}"
            )
        tracked_users = self.tracked_user_repository.list_users_for_thread(thread_id)
        if not tracked_users:
            return (
                f"**{self._localizer.text('show.sections.tracked_users', language=language)}**\n"
                f"{self._localizer.text('show.empty.tracked_users', language=language)}"
            )
        rows: list[str] = []
        for tracked_user in tracked_users:
            twitch_user = await self._resolve_user_by_id(tracked_user.twitch_user_id)
            rows.append(f"- {format_twitch_code_link(display_name=twitch_user.display_name, login=twitch_user.login)}")
        return f"**{self._localizer.text('show.sections.tracked_users', language=language)}**\n" + "\n".join(rows)

    def _render_permissions_section(self, thread: ThreadRecord) -> str:
        language = self._localizer.language_for_thread(thread)
        rows = [f"- <@{thread.owner_id}>\n  {self._localizer.text('show.permission.owner', language=language)}"]
        if self.permission_repository is None:
            return f"**{self._localizer.text('show.sections.permissions', language=language)}**\n" + "\n".join(rows)
        grants = self.permission_repository.list_for_thread(thread_id=thread.thread_id)
        for grant in grants:
            labels = explicit_permission_labels(grant.permissions)
            rendered = (
                "\n".join(f"  - {self._permission_label(label, language=language)}" for label in labels)
                if labels
                else f"  - {self._localizer.text('show.permission.none', language=language)}"
            )
            rows.append(f"- <@{grant.discord_user_id}>\n{rendered}")
        return f"**{self._localizer.text('show.sections.permissions', language=language)}**\n" + "\n".join(rows)

    async def _format_pattern_row(self, pattern: PatternRecord, *, language: str) -> str:
        """Render one compact row containing all identifying pattern fields."""
        parts = [
            self._localizer.text(
                "show.pattern.line",
                language=language,
                TYPE="Regex" if pattern.is_regex else "Ping",
                ID=pattern.p_index,
            ),
            "  "
            + self._localizer.text(
                "show.pattern.text",
                language=language,
                TEXT=pattern.regex,
            ),
        ]
        details = await self._describe_pattern_details(pattern, language=language)
        parts.extend(f"  {detail}" for detail in details)
        return "\n".join(parts)

    async def _format_auto_reply_row(
        self,
        pattern: PatternRecord,
        reply: ReplyRecord,
        *,
        language: str,
    ) -> str:
        """Render one compact row for an attached auto-reply."""
        details = [self._localizer.text("show.reply.line", language=language, ID=pattern.p_index)]
        trigger = self._format_show_code_unescaped(pattern.regex)
        response = self._format_show_code_unescaped(reply.reply_message)
        details.append("  " + self._localizer.text("show.reply.trigger", language=language, TEXT=trigger))
        details.append("  " + self._localizer.text("show.reply.reply", language=language, TEXT=response))
        return "\n".join(details)

    async def _format_adapter_event_action_row(
        self,
        event: AdapterEventRecord,
        action: AdapterEventActionRecord,
        *,
        language: str,
    ) -> str:
        channel_user = await self._resolve_channel_by_id(event.subject_id)
        response = self._format_show_code_unescaped(action.message_template or "")
        state_label = STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key)
        details = [self._localizer.text("show.event_reply.line", language=language, STATE=state_label)]
        details.append(
            "  "
            + self._localizer.text(
                "show.event_reply.channel",
                language=language,
                DISPLAY_NAME=channel_user.display_name,
                LOGIN=channel_user.login,
            )
        )
        details.append("  " + self._localizer.text("show.event_reply.reply", language=language, TEXT=response))
        if action.disabled:
            details.append("  " + self._localizer.text("show.event_reply.disabled", language=language))
        return "\n".join(details)

    async def _describe_pattern_details(self, pattern: PatternRecord, *, language: str) -> list[str]:
        details: list[str] = []
        if pattern.channel_scope_mode != "all_tracked":
            channel_names = await self._resolve_twitch_links(pattern.channel_scope_ids)
            if pattern.channel_scope_mode == "only_selected":
                details.append(self._localizer.text("common.scope.only_in", language=language, ITEMS=", ".join(channel_names)))
            elif pattern.channel_scope_mode == "all_except_selected":
                details.append(
                    self._localizer.text(
                        "common.scope.all_tracked_channels_except",
                        language=language,
                        ITEMS=", ".join(channel_names),
                    )
                )
        if pattern.user_scope_mode != "all_users":
            user_names = await self._resolve_twitch_names(pattern.user_scope_ids)
            if pattern.user_scope_mode == "only_selected":
                details.append(self._localizer.text("common.scope.only_from", language=language, ITEMS=", ".join(user_names)))
            elif pattern.user_scope_mode == "all_except_selected":
                details.append(self._localizer.text("common.scope.everyone_except", language=language, ITEMS=", ".join(user_names)))
            elif pattern.user_scope_mode == "all_tracked":
                details.append(self._localizer.text("common.scope.all_tracked_users", language=language))
            elif pattern.user_scope_mode == "all_tracked_except_selected":
                details.append(
                    self._localizer.text(
                        "common.scope.all_tracked_users_except",
                        language=language,
                        ITEMS=", ".join(user_names),
                    )
                )
        if pattern.sub_state != "all":
            details.append(
                self._localizer.text(
                    "show.pattern.subscribers_only" if pattern.sub_state == "subs" else "show.pattern.non_subscribers_only",
                    language=language,
                )
            )
        if pattern.offline_state != "both":
            details.append(
                self._localizer.text(
                    "show.pattern.only_while_live" if pattern.offline_state == "online" else "show.pattern.only_while_offline",
                    language=language,
                )
            )
        if pattern.case_sensitive:
            details.append(self._localizer.text("show.pattern.case_sensitive", language=language))
        if pattern.color:
            details.append(self._localizer.text("show.pattern.custom_color", language=language, COLOR=pattern.color))
        details.append(self._localizer.text("show.pattern.priority", language=language, PRIORITY=pattern.priority))
        if pattern.disabled:
            details.append(self._localizer.text("show.pattern.disabled", language=language))
        return details

    async def _resolve_twitch_links(
        self,
        twitch_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self._resolve_channel_by_id(twitch_id)
            resolved.append(format_twitch_code_link(display_name=user.display_name, login=user.login))
        return tuple(resolved)

    async def _resolve_twitch_names(
        self,
        twitch_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self._resolve_user_by_id(twitch_id)
            resolved.append(format_twitch_code_link(display_name=user.display_name, login=user.login))
        return tuple(resolved)

    async def _render_account_section(self, thread: ThreadRecord) -> tuple[str, str | None]:
        language = self._localizer.language_for_thread(thread)
        title = self._localizer.text("show.sections.account", language=language)
        rows: list[str] = []
        thumbnail_url = None
        account = (
            None
            if self.account_repository is None or thread.account_id is None
            else self.account_repository.get_by_account_id(thread.account_id)
        )
        if account is not None:
            twitch_user = await self._resolve_user_by_id(account.twitch_user_id)
            thumbnail_url = twitch_user.profile_image_url
            rows.append(
                self._localizer.text(
                    "show.account.linked",
                    language=language,
                    USER=f"<@{account.discord_user_id}>",
                    TWITCH=format_twitch_code_link(display_name=twitch_user.display_name, login=twitch_user.login),
                )
            )
            rows.append(
                self._localizer.text(
                    "show.account.token_status",
                    language=language,
                    STATUS=self._localizer.text(
                        "show.account.token_available" if account.access_token else "show.account.token_missing",
                        language=language,
                    ),
                )
            )
        pending = (
            None
            if self.device_flow_repository is None
            else self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)
        )
        if pending is not None:
            rows.append(
                self._localizer.text(
                    "show.account.pending",
                    language=language,
                    USER=f"<@{pending.discord_user_id}>",
                    STATUS=pending.status,
                    USER_CODE=pending.user_code,
                )
            )
        if not rows:
            rows.append(self._localizer.text("show.account.empty", language=language))
        return f"**{title}**\n" + "\n".join(f"- {row}" for row in rows), thumbnail_url

    def _permission_label(self, label: str, *, language: str) -> str:
        key = f"show.permission.{label}"
        try:
            return self._localizer.text(key, language=language)
        except ValueError:
            return label.replace("_", " ").capitalize()

    @property
    def _localizer(self) -> Localizer:
        return self.localizer or Localizer.from_directory()

    @staticmethod
    def _format_show_code_unescaped(text: str) -> str:
        if "`" in text:
            return text
        return f"`{text}`"

    async def _resolve_channel_by_id(self, user_id: str):
        get_channel = getattr(self.twitch_api, "get_channel_by_id", None)
        if callable(get_channel):
            return await get_channel(user_id)
        return await self._resolve_user_by_id(user_id)

    async def _resolve_user_by_id(self, user_id: str):
        cached_lookup = getattr(self.twitch_api, "get_cached_user_by_id", None)
        normalized_user_id = user_id.strip()
        if callable(cached_lookup) and normalized_user_id:
            cached = cached_lookup(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)

