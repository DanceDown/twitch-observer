"""Focused `/show` renderer for linked account state."""

from __future__ import annotations

from dataclasses import dataclass

from src.database.connection import ThreadRecord, TwitchAccountRepository, TwitchDeviceFlowRepository
from src.localization import Localizer

from .support import ShowFormattingService, ShowTwitchSubjectResolver


@dataclass(slots=True)
class ShowAccountRenderer:
    account_repository: TwitchAccountRepository | None
    device_flow_repository: TwitchDeviceFlowRepository | None
    resolver: ShowTwitchSubjectResolver
    formatter: ShowFormattingService
    localizer: Localizer

    async def render(self, thread: ThreadRecord) -> tuple[str, str | None]:
        language = self.localizer.language_for_thread(thread)
        rows: list[str] = []
        thumbnail_url = None
        account = (
            None
            if self.account_repository is None or thread.account_id is None
            else await self.account_repository.get_by_account_id(thread.account_id)
        )
        if account is not None:
            twitch_user = await self.resolver.resolve_user_by_id(account.twitch_user_id)
            thumbnail_url = twitch_user.profile_image_url
            rows.append(
                self.localizer.text(
                    "show.account.linked",
                    language=language,
                    USER=self.formatter.mention(account.discord_user_id),
                    DISPLAY_NAME=twitch_user.display_name,
                    LOGIN=twitch_user.login,
                )
            )
            rows.append(
                self.localizer.text(
                    "show.account.token_status",
                    language=language,
                    STATUS=self.localizer.text(
                        "show.account.token_available" if account.access_token else "show.account.token_missing",
                        language=language,
                    ),
                )
            )
        pending = (
            None
            if self.device_flow_repository is None
            else await self.device_flow_repository.get_by_discord_channel_id(thread.discord_channel_id)
        )
        if pending is not None:
            rows.append(
                self.localizer.text(
                    "show.account.pending",
                    language=language,
                    USER=self.formatter.mention(pending.discord_user_id),
                    STATUS=pending.status,
                    USER_CODE=pending.user_code,
                )
            )
        if not rows:
            rows.append(self.localizer.text("show.account.empty", language=language))
        return (
            self.formatter.render_section(
                "show.account.section",
                self.localizer.text("show.account.rows", language=language, ITEMS=tuple(rows)),
                language=language,
            ),
            thumbnail_url,
        )
