"""Rendering helpers for `/show` configuration overviews."""

from __future__ import annotations

from dataclasses import dataclass

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
from src.localization import Localizer
from src.services.twitch_gateways import TwitchDirectoryGateway
from src.services.twitch_runtime import (
    CHANNEL_SUBJECT_TYPE,
    STREAM_EVENT_KEY_TO_STATE,
    TWITCH_ADAPTER_KEY,
    TWITCH_SEND_MESSAGE_ACTION,
)
from src.utils.discord_embeds import format_twitch_code_link
from src.utils.permissions import explicit_permission_labels


@dataclass(slots=True)
class ShowSectionRenderer:
    """Render localized `/show` sections from persisted configuration."""

    thread_repository: ThreadRepository
    channel_repository: ChannelRepository
    pattern_repository: PatternRepository
    reply_repository: ReplyRepository
    twitch_api: TwitchDirectoryGateway
    tracked_user_repository: TrackedUserRepository | None = None
    adapter_event_repository: AdapterEventRepository | None = None
    adapter_event_action_repository: AdapterEventActionRepository | None = None
    localizer: Localizer | None = None
    permission_repository: UserPermissionRepository | None = None
    account_repository: TwitchAccountRepository | None = None
    device_flow_repository: TwitchDeviceFlowRepository | None = None

    async def render_channels_section(self, thread_id: int) -> str:
        """Render the tracked Twitch channels for one Discord configuration root."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        channels = self.channel_repository.list_channels_for_thread(thread_id)
        if not channels:
            return self.section(
                self._localizer.text("show.sections.tracked_channels", language=language),
                self._localizer.text("show.empty.tracked_channels", language=language),
                language=language,
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
                self.stream_state_label(STREAM_EVENT_KEY_TO_STATE[item.event_key], language=language)
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
            twitch_user = await self.resolve_channel_by_id(channel.twitch_channel_id)
            details: list[str] = []
            if channel.color:
                details.append(
                    self._localizer.text(
                        "show.channel.custom_color",
                        language=language,
                        COLOR=channel.color,
                    )
                )
            if channel.is_live is not None:
                details.append(
                    self._localizer.text(
                        "show.channel.live_state",
                        language=language,
                        STATE=self.stream_state_label("online" if channel.is_live else "offline", language=language),
                    )
                )
            configured_states = event_state_by_channel_id.get(channel.twitch_channel_id, [])
            if configured_states:
                details.append(
                    self._localizer.text(
                        "show.channel.notifications",
                        language=language,
                        STATES=configured_states,
                    )
                )
            rows.append(
                self.grouped_bullet(
                    format_twitch_code_link(
                        localizer=self._localizer,
                        language=language,
                        display_name=twitch_user.display_name,
                        login=twitch_user.login,
                    ),
                    details,
                    language=language,
                )
            )
        return self.section(
            self._localizer.text("show.sections.tracked_channels", language=language),
            self.raw_lines(rows, language=language),
            language=language,
        )

    async def render_patterns_section(self, thread_id: int, *, title: str) -> str:
        """Render all stored ping and regex rules with dense display IDs."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        patterns = self.pattern_repository.list_patterns_for_thread(
            thread_id,
            is_regex=None,
        )
        if not patterns:
            return self.section(title, self._localizer.text("show.empty.pings", language=language), language=language)
        rows = [
            await self.format_pattern_row(pattern, display_index=display_index, language=language)
            for display_index, pattern in enumerate(patterns, start=1)
        ]
        return self.section(title, self.raw_lines(rows, language=language), language=language)

    async def render_auto_replies_section(self, thread_id: int) -> str:
        """Render all patterns and event-actions that currently send auto-replies."""
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
            return self.section(
                self._localizer.text("show.sections.auto_replies", language=language),
                self._localizer.text("show.empty.auto_replies", language=language),
                language=language,
            )
        rows: list[str] = []
        pattern_display_indices = {
            pattern.pattern_id: display_index
            for display_index, pattern in enumerate(
                self.pattern_repository.list_patterns_for_thread(thread_id),
                start=1,
            )
        }
        for reply in replies:
            pattern = self.pattern_repository.get_pattern_by_id(
                thread_id=thread_id,
                pattern_id=reply.pattern_id,
            )
            if pattern is None:
                continue
            display_index = pattern_display_indices.get(pattern.pattern_id, pattern.pattern_id)
            rows.append(
                await self.format_auto_reply_row(
                    pattern,
                    reply,
                    display_index=display_index,
                    language=language,
                )
            )
        for adapter_event, action in adapter_event_actions:
            rows.append(await self.format_adapter_event_action_row(adapter_event, action, language=language))
        if not rows:
            return self.section(
                self._localizer.text("show.sections.auto_replies", language=language),
                self._localizer.text("show.empty.auto_replies", language=language),
                language=language,
            )
        return self.section(
            self._localizer.text("show.sections.auto_replies", language=language),
            self.raw_lines(rows, language=language),
            language=language,
        )

    async def render_users_section(self, thread_id: int) -> str:
        """Render the tracked Twitch users for one Discord configuration root."""
        thread = self.thread_repository.get_by_thread_id(thread_id)
        language = self._localizer.language_for_thread(thread)
        if self.tracked_user_repository is None:
            return self.section(
                self._localizer.text("show.sections.tracked_users", language=language),
                self._localizer.text("show.empty.tracked_users", language=language),
                language=language,
            )
        tracked_users = self.tracked_user_repository.list_users_for_thread(thread_id)
        if not tracked_users:
            return self.section(
                self._localizer.text("show.sections.tracked_users", language=language),
                self._localizer.text("show.empty.tracked_users", language=language),
                language=language,
            )
        rows: list[str] = []
        for tracked_user in tracked_users:
            twitch_user = await self.resolve_user_by_id(tracked_user.twitch_user_id)
            rows.append(
                format_twitch_code_link(
                    localizer=self._localizer,
                    language=language,
                    display_name=twitch_user.display_name,
                    login=twitch_user.login,
                )
            )
        return self.section(
            self._localizer.text("show.sections.tracked_users", language=language),
            self.bullets(rows, language=language),
            language=language,
        )

    def render_permissions_section(self, thread: ThreadRecord) -> str:
        """Render the permission overview for one Discord context."""
        language = self._localizer.language_for_thread(thread)
        user_entries: list[str] = []
        permission_msg = self._localizer.value("show.show_permissions", language=language)
        if not isinstance(permission_msg, dict):
            raise ValueError("show.show_permissions must be an object.")
        body_template = permission_msg.get("body")
        user_list_item = permission_msg.get("user_list_item")
        permission_list_item = permission_msg.get("permission_list_item")
        if not isinstance(body_template, str) or not isinstance(user_list_item, str) or not isinstance(permission_list_item, str):
            raise ValueError("show.show_permissions must define body, user_list_item and permission_list_item.")

        owner_permissions = self._localizer.render(
            permission_list_item,
            PERMISSION=self._localizer.text("show.permission.owner", language=language),
        )
        user_entries.append(
            self._localizer.render(
                user_list_item,
                USERNAME=self.mention(thread.owner_id, language=language),
                PERMISSION_LIST=owner_permissions,
            )
        )

        if self.permission_repository is None:
            return self._localizer.render(body_template, USER_LIST="\n".join(user_entries))

        grants = self.permission_repository.list_for_thread(thread_id=thread.thread_id)
        for grant in grants:
            labels = explicit_permission_labels(grant.permissions)
            rendered = (
                [self.permission_label(label, language=language) for label in labels]
                if labels
                else [self._localizer.text("show.permission.none", language=language)]
            )
            permission_lines = "\n".join(
                self._localizer.render(permission_list_item, PERMISSION=item)
                for item in rendered
            )
            user_entries.append(
                self._localizer.render(
                    user_list_item,
                    USERNAME=self.mention(grant.discord_user_id, language=language),
                    PERMISSION_LIST=permission_lines,
                )
            )
        return self._localizer.render(body_template, USER_LIST="\n".join(user_entries))

    async def render_account_section(self, thread: ThreadRecord) -> tuple[str, str | None]:
        """Render linked account and pending device-flow details."""
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
            twitch_user = await self.resolve_user_by_id(account.twitch_user_id)
            thumbnail_url = twitch_user.profile_image_url
            rows.append(
                self._localizer.text(
                    "show.account.linked",
                    language=language,
                    USER=self.mention(account.discord_user_id, language=language),
                    TWITCH=format_twitch_code_link(
                        localizer=self._localizer,
                        language=language,
                        display_name=twitch_user.display_name,
                        login=twitch_user.login,
                    ),
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
                    USER=self.mention(pending.discord_user_id, language=language),
                    STATUS=pending.status,
                    USER_CODE=pending.user_code,
                )
            )
        if not rows:
            rows.append(self._localizer.text("show.account.empty", language=language))
        return self.section(title, self.bullets(rows, language=language), language=language), thumbnail_url

    async def format_pattern_row(self, pattern: PatternRecord, *, display_index: int, language: str) -> str:
        """Render one compact row containing all identifying pattern fields."""
        head = self._localizer.text(
            "show.pattern.line",
            language=language,
            TYPE=self._localizer.text(
                "results.pattern.type.regex" if pattern.is_regex else "results.pattern.type.ping",
                language=language,
            ),
            ID=display_index,
        )
        details = [
            self._localizer.text(
                "show.pattern.text",
                language=language,
                TEXT=pattern.regex,
            )
        ]
        details.extend(await self.describe_pattern_details(pattern, language=language))
        return self.grouped_bullet(head, details, language=language)

    async def format_auto_reply_row(
        self,
        pattern: PatternRecord,
        reply: ReplyRecord,
        *,
        display_index: int,
        language: str,
    ) -> str:
        """Render one compact row for an attached auto-reply."""
        details = [
            self._localizer.text("show.reply.trigger", language=language, TEXT=pattern.regex),
            self._localizer.text("show.reply.reply", language=language, TEXT=reply.reply_message),
        ]
        return self.grouped_bullet(
            self._localizer.text("show.reply.line", language=language, ID=display_index),
            details,
            language=language,
        )

    async def format_adapter_event_action_row(
        self,
        event: AdapterEventRecord,
        action: AdapterEventActionRecord,
        *,
        language: str,
    ) -> str:
        """Render one compact row for a source-driven auto-reply action."""
        channel_user = await self.resolve_channel_by_id(event.subject_id)
        state_label = self.stream_state_label(STREAM_EVENT_KEY_TO_STATE.get(event.event_key, event.event_key), language=language)
        details = [
            self._localizer.text(
                "show.event_reply.channel",
                language=language,
                DISPLAY_NAME=channel_user.display_name,
                LOGIN=channel_user.login,
            ),
            self._localizer.text("show.event_reply.reply", language=language, TEXT=action.message_template or ""),
        ]
        if action.disabled:
            details.append(self._localizer.text("show.event_reply.disabled", language=language))
        return self.grouped_bullet(
            self._localizer.text("show.event_reply.line", language=language, STATE=state_label),
            details,
            language=language,
        )

    async def describe_pattern_details(self, pattern: PatternRecord, *, language: str) -> list[str]:
        """Render the optional modifiers for a pattern."""
        details: list[str] = []
        if pattern.channel_scope_mode != "all_tracked":
            channel_names = await self.resolve_twitch_links(pattern.channel_scope_ids, language=language)
            if pattern.channel_scope_mode == "only_selected":
                details.append(
                    self._localizer.text(
                        "show.pattern.where",
                        language=language,
                        VALUE=self._localizer.text("common.scope.only_in", language=language, ITEMS=channel_names),
                    )
                )
            elif pattern.channel_scope_mode == "all_except_selected":
                details.append(
                    self._localizer.text(
                        "show.pattern.where",
                        language=language,
                        VALUE=self._localizer.text(
                            "common.scope.all_tracked_channels_except",
                            language=language,
                            ITEMS=channel_names,
                        ),
                    )
                )
        if pattern.user_scope_mode != "all_users":
            user_names = await self.resolve_twitch_names(pattern.user_scope_ids, language=language)
            if pattern.user_scope_mode == "only_selected":
                details.append(
                    self._localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self._localizer.text("common.scope.only_from", language=language, ITEMS=user_names),
                    )
                )
            elif pattern.user_scope_mode == "all_except_selected":
                details.append(
                    self._localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self._localizer.text(
                            "common.scope.everyone_except",
                            language=language,
                            ITEMS=user_names,
                        ),
                    )
                )
            elif pattern.user_scope_mode == "all_tracked":
                details.append(
                    self._localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self._localizer.text("common.scope.all_tracked_users", language=language),
                    )
                )
            elif pattern.user_scope_mode == "all_tracked_except_selected":
                details.append(
                    self._localizer.text(
                        "show.pattern.who",
                        language=language,
                        VALUE=self._localizer.text(
                            "common.scope.all_tracked_users_except",
                            language=language,
                            ITEMS=user_names,
                        ),
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

    async def resolve_twitch_links(
        self,
        twitch_ids: tuple[str, ...],
        *,
        language: str,
    ) -> tuple[str, ...]:
        """Resolve a list of Twitch user IDs to rendered markdown links."""
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self.resolve_channel_by_id(twitch_id)
            resolved.append(
                format_twitch_code_link(
                    localizer=self._localizer,
                    language=language,
                    display_name=user.display_name,
                    login=user.login,
                )
            )
        return tuple(resolved)

    async def resolve_twitch_names(
        self,
        twitch_ids: tuple[str, ...],
        *,
        language: str,
    ) -> tuple[str, ...]:
        """Resolve a list of Twitch user IDs to rendered markdown links."""
        resolved: list[str] = []
        for twitch_id in twitch_ids:
            user = await self.resolve_user_by_id(twitch_id)
            resolved.append(
                format_twitch_code_link(
                    localizer=self._localizer,
                    language=language,
                    display_name=user.display_name,
                    login=user.login,
                )
            )
        return tuple(resolved)

    def permission_label(self, label: str, *, language: str) -> str:
        """Render one permission label using localization when available."""
        key = f"show.permission.{label}"
        try:
            return self._localizer.text(key, language=language)
        except ValueError:
            return label.replace("_", " ").capitalize()

    def section(self, title: str, body: str, *, language: str) -> str:
        """Render one localized section wrapper."""
        return self._localizer.text("common.fragments.section", language=language, TITLE=title, SECTION_BODY=body)

    def bullets(self, items: list[str], *, language: str) -> str:
        """Render plain bullet items."""
        return "\n".join(f"- {item}" for item in items)

    def indented_bullets(self, items: list[str], *, language: str) -> str:
        """Render indented bullet items."""
        return "\n".join(f"  - {item}" for item in items)

    def raw_lines(self, items: list[str], *, language: str) -> str:
        """Join already-rendered lines without adding prefixes."""
        return "\n".join(items)

    def section_breaks(self, items: list[str], *, language: str) -> str:
        """Join full sections with the standard section separator."""
        return "\n\n".join(items)

    def comma_list(self, items: list[str] | tuple[str, ...], *, language: str) -> str:
        """Render inline comma-separated fragments."""
        return ", ".join(items)

    def grouped_bullet(self, head: str, details: list[str], *, language: str) -> str:
        """Render one main bullet with optional indented detail bullets."""
        rendered = [self.bullets([head], language=language)]
        if details:
            rendered.append(self.indented_bullets(details, language=language))
        return self.raw_lines(rendered, language=language)

    def mention(self, user_id: int, *, language: str) -> str:
        """Render one Discord user mention."""
        return self._localizer.text("common.fragments.discord_user_mention", language=language, USER_ID=user_id)

    def stream_state_label(self, value: str, *, language: str) -> str:
        """Render a localized stream-state label."""
        key = (
            "discord.live_state_ui.states.stream.online"
            if value in {"online", "live", "stream.online"}
            else "discord.live_state_ui.states.stream.offline"
        )
        return self._localizer.text(key, language=language)

    async def resolve_channel_by_id(self, user_id: str):
        """Resolve one Twitch channel subject by Twitch ID."""
        return await self.twitch_api.get_channel_by_id(user_id)

    async def resolve_user_by_id(self, user_id: str):
        """Resolve one Twitch user by Twitch ID, preferring cached metadata."""
        normalized_user_id = user_id.strip()
        if normalized_user_id:
            cached = self.twitch_api.get_cached_user_by_id(normalized_user_id)
            if cached is not None:
                return cached
        return await self.twitch_api.get_user_by_id(user_id)

    @property
    def _localizer(self) -> Localizer:
        return self.localizer or Localizer.from_directory()
