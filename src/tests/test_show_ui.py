from __future__ import annotations

import discord

from src.entrypoints.discord.ui.show_ui import ShowPaginationView, build_show_pages
from src.events.discord_results import DiscordCommandResult, DiscordResultStyle
from src.localization import Localizer


def test_build_show_pages_repeats_header_and_keeps_items_together() -> None:
    item_one = "- one\n  detail"
    item_two = "- two\n  detail"
    item_three = "- three\n  detail"
    first_page = f"**Pings**\n{item_one}\n{item_two}"
    message = f"{first_page}\n{item_three}"

    pages = build_show_pages(message, description_limit=len(first_page), item_prefix="- ")

    assert len(pages) == 2
    assert pages[0] == first_page
    assert pages[1].endswith(item_three)


def test_build_show_pages_keeps_collecting_items_after_first_page_break() -> None:
    item_one = "- one\n  detail"
    item_two = "- two\n  detail"
    item_three = "- six\n  detail"
    item_four = "- ten\n  detail"
    first_page = f"**Pings**\n{item_one}\n{item_two}"
    second_page = f"**Pings**\n{item_three}\n{item_four}"
    message = f"{first_page}\n{item_three}\n{item_four}"

    pages = build_show_pages(message, description_limit=len(first_page), item_prefix="- ")

    assert pages == (first_page, second_page)


def test_build_show_pages_splits_oversized_single_item_when_needed() -> None:
    pages = build_show_pages("**Pings**\n- " + ("x" * 25), description_limit=20, item_prefix="- ")

    assert len(pages) == 3
    assert all(page.startswith("**Pings**\n") for page in pages)
    assert all(len(page) <= 20 for page in pages)


def test_show_pagination_view_sets_footer_and_button_states() -> None:
    detail = "x" * 2100
    result = DiscordCommandResult(
        title="Konfigurationsübersicht",
        message=f"**Pings**\n- one\n  {detail}\n- two\n  {detail}\n- three\n  {detail}",
        style=DiscordResultStyle.INFO,
        ephemeral=True,
    )

    localizer = Localizer.from_directory()
    view = ShowPaginationView(owner_id=200, result=result, localizer=localizer, language="german", item_prefix="- ")
    view._page_index = 0
    view._sync_button_states()
    embed = view.render_embed()
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert embed.footer.text is not None
    assert len(buttons) == 2
    assert buttons[0].disabled is True
    assert buttons[1].disabled is False
    assert embed.footer.text.startswith("Seite ")
