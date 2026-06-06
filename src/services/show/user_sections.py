"""Focused `/show` renderers for users and permissions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ThreadRecord, TrackedUserRepository, UserPermissionRepository
from src.localization import Localizer
from src.utils.permissions import explicit_permission_labels

from .support import ShowFormattingService, ShowTwitchSubjectResolver


@dataclass(slots=True)
class ShowUsersRenderer:
    tracked_user_repository: TrackedUserRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        empty_text = self.localizer.text("show.tracked_users.empty", language=language)
        if self.tracked_user_repository is None:
            return self.formatter.render_section("show.tracked_users.section", empty_text, language=language)
        tracked_users = await self.tracked_user_repository.list_users_for_thread(thread.thread_id)
        if not tracked_users:
            return self.formatter.render_section("show.tracked_users.section", empty_text, language=language)
        await self.resolver.preload_user_ids(tuple(tracked_user.twitch_user_id for tracked_user in tracked_users))
        rows = []
        for tracked_user in tracked_users:
            twitch_user = await self.resolver.resolve_user_by_id(tracked_user.twitch_user_id)
            rows.append({"DISPLAY_NAME": twitch_user.display_name, "LOGIN": twitch_user.login})
        return self.formatter.render_section(
            "show.tracked_users.section",
            self.localizer.text("show.tracked_users.rows", language=language, ITEMS=tuple(rows)),
            language=language,
        )


@dataclass(slots=True)
class ShowPermissionsRenderer:
    permission_repository: UserPermissionRepository | None
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        user_entries = [
            self._render_user_entry(
                user_id=thread.owner_id,
                permissions=(
                    self.localizer.text("show.show_permissions.permission_label.owner", language=language),
                ),
                language=language,
            )
        ]
        if self.permission_repository is not None:
            for grant in await self.permission_repository.list_for_thread(thread_id=thread.thread_id):
                labels = explicit_permission_labels(grant.permissions)
                rendered = (
                    [self.formatter.permission_label(label, language=language) for label in labels]
                    if labels
                    else [self.localizer.text("show.show_permissions.permission_label.none", language=language)]
                )
                user_entries.append(
                    self._render_user_entry(
                        user_id=grant.discord_user_id,
                        permissions=tuple(rendered),
                        language=language,
                    )
                )
        return self.formatter.render_section(
            "show.show_permissions.section",
            self.localizer.render(
                self._permissions_body_template(language=language),
                USER_LIST=self.formatter.render_permissions_user_list(user_entries, language=language),
            ),
            language=language,
        )

    def _render_user_entry(
        self,
        *,
        user_id: int,
        permissions: tuple[str, ...],
        language: str,
    ) -> str:
        return self.localizer.render(
            self._permissions_user_list_item(language=language),
            USERNAME=self.formatter.mention(user_id),
            PERMISSION_LIST=self.localizer.text(
                "show.show_permissions.permission_list",
                language=language,
                PERMISSIONS=permissions,
            ),
        )

    def _permissions_body_template(self, *, language: str) -> str:
        permission_msg = self.localizer.value("show.show_permissions", language=language)
        if not isinstance(permission_msg, dict):
            raise ValueError("show.show_permissions must be an object.")
        body_template = permission_msg.get("body")
        if not isinstance(body_template, str):
            raise ValueError("show.show_permissions must define body and user_list_item.")
        return body_template

    def _permissions_user_list_item(self, *, language: str) -> str:
        permission_msg = self.localizer.value("show.show_permissions", language=language)
        if not isinstance(permission_msg, dict):
            raise ValueError("show.show_permissions must be an object.")
        user_list_item = permission_msg.get("user_list_item")
        if not isinstance(user_list_item, str):
            raise ValueError("show.show_permissions must define body and user_list_item.")
        return user_list_item
