from __future__ import annotations

"""Discord UI for `/show`."""

from contextlib import suppress

import discord

from src.events.event_bus import EventBus
from src.events.event_types import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer
from src.utils.discord_embeds import build_result_embed

from ..dispatch import dispatch_show_command
from ..helpers import send_initial_result
from ..ui_data import DiscordUIDataProvider
from .shared import resolve_context_language


SHOW_EMBED_DESCRIPTION_LIMIT = 4096


def build_show_pages(
    message: str,
    *,
    description_limit: int = SHOW_EMBED_DESCRIPTION_LIMIT,
    empty_message: str = "No configuration entries found.",
) -> tuple[str, ...]:
    """Split one `/show` result into embed-safe pages while keeping bullet items intact."""
    normalized = message.strip()
    if not normalized:
        return (empty_message,)
    if len(normalized) <= description_limit:
        return (normalized,)

    header, items = _extract_show_header_and_items(normalized)
    if not items:
        return _split_plain_text(normalized, description_limit)

    prefix = f"{header}\n" if header else ""
    available_item_length = max(1, description_limit - len(prefix))
    pages: list[str] = []
    current_items: list[str] = []
    for item in items:
        candidate_items = [*current_items, item]
        candidate_body = "\n".join(candidate_items)
        candidate_page = f"{prefix}{candidate_body}" if prefix else candidate_body
        if len(candidate_page) <= description_limit:
            current_items = candidate_items
            continue
        if current_items:
            current_body = "\n".join(current_items)
            pages.append(f"{prefix}{current_body}" if prefix else current_body)
            current_items = []
        for oversized_part in _split_plain_text(item, available_item_length):
            pages.append(f"{prefix}{oversized_part}" if prefix else oversized_part)

    if current_items:
        current_body = "\n".join(current_items)
        pages.append(f"{prefix}{current_body}" if prefix else current_body)
    return tuple(pages)


def _extract_show_header_and_items(message: str) -> tuple[str, tuple[str, ...]]:
    """Return the section heading and grouped bullet blocks from a rendered `/show` message."""
    lines = message.splitlines()
    first_item_index = next((index for index, line in enumerate(lines) if line.startswith("- ")), None)
    if first_item_index is None:
        return message, ()

    header = "\n".join(lines[:first_item_index]).strip()
    items: list[str] = []
    current_item: list[str] = []
    for line in lines[first_item_index:]:
        if line.startswith("- "):
            if current_item:
                items.append("\n".join(current_item))
            current_item = [line]
            continue
        current_item.append(line)
    if current_item:
        items.append("\n".join(current_item))
    return header, tuple(items)


def _split_plain_text(text: str, limit: int) -> tuple[str, ...]:
    """Split a plain text block by lines first and by characters as a last resort."""
    normalized = text.strip()
    if not normalized:
        return ("",)
    if len(normalized) <= limit:
        return (normalized,)

    parts: list[str] = []
    current_lines: list[str] = []
    for line in normalized.splitlines():
        candidate_lines = [*current_lines, line]
        candidate = "\n".join(candidate_lines)
        if current_lines and len(candidate) > limit:
            parts.extend(_split_by_characters("\n".join(current_lines), limit))
            current_lines = [line]
            continue
        current_lines = candidate_lines

    if current_lines:
        parts.extend(_split_by_characters("\n".join(current_lines), limit))
    return tuple(parts)


def _split_by_characters(text: str, limit: int) -> tuple[str, ...]:
    """Fallback splitter for a single line or block that still exceeds the limit."""
    return tuple(text[index : index + limit] for index in range(0, len(text), limit) if text[index : index + limit])


class ShowPaginationView(discord.ui.View):
    """Ephemeral paginator used by `/show` when the rendered section spans multiple pages."""

    def __init__(self, *, owner_id: int, result: DiscordCommandResult, localizer: Localizer, language: str) -> None:
        super().__init__(timeout=840)
        self._owner_id = owner_id
        self._result = result
        self._localizer = localizer
        self._language = language
        self._pages = build_show_pages(
            result.message,
            empty_message=localizer.text("discord.show_ui.pagination.empty_message", language=language),
        )
        self._page_index = 0
        self.bound_message: discord.InteractionMessage | None = None
        self.previous_page.label = localizer.text("discord.show_ui.pagination.previous", language=language)
        self.next_page.label = localizer.text("discord.show_ui.pagination.next", language=language)
        self._sync_button_states()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Limit the paginator to the user who opened the `/show` modal."""
        if interaction.user.id == self._owner_id:
            return True
        await interaction.response.send_message(
            embed=build_result_embed(
                self._localizer.result(
                    "discord.show_ui.pagination.locked",
                    language=self._language,
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            ),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        """Disable the controls once the ephemeral paginator expires."""
        self._sync_button_states(disabled=True)
        if self.bound_message is not None:
            with suppress(discord.HTTPException):
                await self.bound_message.edit(view=self)

    def render_embed(self) -> discord.Embed:
        """Render the current `/show` page using the shared embed styling."""
        embed = build_result_embed(self._result)
        embed.description = self._pages[self._page_index]
        embed.set_footer(
            text=self._localizer.text(
                "discord.show_ui.pagination.footer",
                language=self._language,
                CURRENT=self._page_index + 1,
                TOTAL=len(self._pages),
            )
        )
        return embed

    def _sync_button_states(self, *, disabled: bool = False) -> None:
        self.previous_page.disabled = disabled or self._page_index <= 0
        self.next_page.disabled = disabled or self._page_index >= len(self._pages) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Show the previous `/show` page in the same ephemeral message."""
        self._page_index = max(0, self._page_index - 1)
        self._sync_button_states()
        await interaction.response.edit_message(embed=self.render_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        """Show the next `/show` page in the same ephemeral message."""
        self._page_index = min(len(self._pages) - 1, self._page_index + 1)
        self._sync_button_states()
        await interaction.response.edit_message(embed=self.render_embed(), view=self)


class ShowSectionModal(discord.ui.Modal):
    """Collect the requested `/show` section with a single modal."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        discord_channel_id: int,
        requester_id: int,
        ui_data_provider: DiscordUIDataProvider,
        localizer: Localizer,
    ) -> None:
        language = resolve_context_language(
            localizer=localizer,
            data_provider=ui_data_provider,
            discord_channel_id=discord_channel_id,
        )
        super().__init__(title=localizer.text("discord.show_ui.modal.title", language=language), timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id
        self._localizer = localizer
        self._language = language
        self.section = discord.ui.Label(
            text=localizer.text("discord.show_ui.modal.section_label", language=language),
            component=discord.ui.RadioGroup(
                options=[
                    discord.RadioGroupOption(label=localizer.text("show.sections.pings", language=language), value="pings"),
                    discord.RadioGroupOption(
                        label=localizer.text("show.sections.auto_replies", language=language),
                        value="auto_replies",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("show.sections.tracked_channels", language=language),
                        value="channels",
                        default=True,
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("show.sections.tracked_users", language=language),
                        value="users",
                    ),
                    discord.RadioGroupOption(
                        label=localizer.text("show.sections.permissions", language=language),
                        value="permissions",
                    ),
                ]
            ),
        )
        self.add_item(self.section)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Render the selected overview section."""
        result = await dispatch_show_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            sections=(self.section.component.value or "channels",),
        )
        if result.style != DiscordResultStyle.INFO or not result.ephemeral:
            await send_initial_result(interaction, result)
            return

        view = ShowPaginationView(
            owner_id=self._requester_id,
            result=result,
            localizer=self._localizer,
            language=self._language,
        )
        await interaction.response.send_message(
            embed=view.render_embed(),
            view=view,
            ephemeral=True,
        )
        view.bound_message = await interaction.original_response()
