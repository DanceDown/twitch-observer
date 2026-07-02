"""Beginner-friendly help text rendering for the Discord control surface."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.connection import ThreadRepository
from src.discord_results import build_result
from src.events.commands import HelpCommand
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer

DEFAULT_HELP_SECTION = "overview"
HELP_SECTIONS = (
    "overview",
    "first_steps",
    "channels",
    "users",
    "pings",
    "auto_replies",
    "live_pings",
    "write",
    "account",
    "permissions",
    "tips",
)


def normalize_help_section(section: str | None) -> str:
    """Normalize one requested help section and fall back to the overview."""
    normalized = (section or "").strip().lower()
    return normalized if normalized in HELP_SECTIONS else DEFAULT_HELP_SECTION


@dataclass(slots=True)
class HelpCommandService:
    """Render localized help sections without requiring a joined context."""

    thread_repository: ThreadRepository | None = None
    localizer: Localizer = field(default_factory=Localizer.from_directory)

    async def handle_command(self, command: HelpCommand) -> DiscordCommandResult:
        """Return one localized help embed for the requested section."""
        language = await self._resolve_language(command)
        section = normalize_help_section(command.section)
        return build_result(
            self.localizer,
            f"results.help.{section}",
            language=language,
            style=DiscordResultStyle.INFO,
            ephemeral=True,
        )

    async def _resolve_language(self, command: HelpCommand) -> str:
        if command.discord_channel_id is not None and self.thread_repository is not None:
            thread = await self.thread_repository.get_by_discord_channel_id(command.discord_channel_id)
            if thread is not None:
                return self.localizer.language_for_thread(thread)
        return self.localizer.resolve_language(command.language_hint)
