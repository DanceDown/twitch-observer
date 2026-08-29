"""Focused `/show` renderers for users and permissions."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ThreadRecord, TrackedUserRepository, UserPermissionRepository
from src.localization import Localizer
from src.utils.permissions import explicit_permission_labels

from .support import ShowTwitchSubjectResolver
from .text import render_empty_section, render_rows, render_section


@dataclass(slots=True)
class ShowUsersRenderer:
    tracked_user_repository: TrackedUserRepository | None
    resolver: ShowTwitchSubjectResolver
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        if self.tracked_user_repository is None:
            return render_empty_section(self.localizer, "show.tracked_users", language=language)
        tracked_users = await self.tracked_user_repository.list_users_for_thread(thread.thread_id)
        if not tracked_users:
            return render_empty_section(self.localizer, "show.tracked_users", language=language)
        await self.resolver.preload_user_ids(tuple(tracked_user.twitch_user_id for tracked_user in tracked_users))
        rows = []
        for tracked_user in tracked_users:
            twitch_user = await self.resolver.resolve_user_by_id(tracked_user.twitch_user_id)
            rows.append({"display_name": twitch_user.display_name, "login": twitch_user.login})
        return render_section(
            self.localizer,
            "show.tracked_users",
            language=language,
            section_body=render_rows(self.localizer, "show.tracked_users", language=language, items=tuple(rows)),
        )


@dataclass(slots=True)
class ShowPermissionsRenderer:
    permission_repository: UserPermissionRepository | None
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> str:
        language = self.localizer.language_for_thread(thread)
        user_entries = [
            {
                "user_id": thread.owner_id,
                "permission_list": self.localizer.text(
                    "show.permissions.permission_list",
                    language=language,
                    sources={"view": {"permissions": (self.localizer.text("show.permissions.permission_label.owner", language=language),)}},
                ),
            }
        ]
        if self.permission_repository is not None:
            for grant in await self.permission_repository.list_for_thread(thread_id=thread.thread_id):
                labels = explicit_permission_labels(grant.permissions)
                rendered = (
                    [self.localizer.text(f"show.permissions.permission_label.{label}", language=language) for label in labels]
                    if labels
                    else [self.localizer.text("show.permissions.permission_label.none", language=language)]
                )
                user_entries.append(
                    {
                        "user_id": grant.discord_user_id,
                        "permission_list": self.localizer.text(
                            "show.permissions.permission_list",
                            language=language,
                            sources={"view": {"permissions": tuple(rendered)}},
                        ),
                    }
                )
        return render_section(
            self.localizer,
            "show.permissions",
            language=language,
            section_body=self.localizer.text(
                "show.permissions.body",
                language=language,
                sources={"view": {"user_list": tuple(user_entries)}},
            ),
        )
