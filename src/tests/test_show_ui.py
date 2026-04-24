from __future__ import annotations

import discord

from src.adapters.discord.ui.show_ui import ShowPaginationView, build_show_pages
from src.events.event_types import DiscordCommandResult, DiscordResultStyle


def _find_button(view: discord.ui.View, label: str) -> discord.ui.Button:
    for child in view.children:
        if isinstance(child, discord.ui.Button) and child.label == label:
            return child
    raise AssertionError(f"Button {label!r} not found.")


def test_build_show_pages_repeats_header_and_keeps_items_together() -> None:
    item_one = "- one\n  detail"
    item_two = "- two\n  detail"
    item_three = "- three\n  detail"
    first_page = f"**Pings**\n{item_one}\n{item_two}"
    message = f"{first_page}\n{item_three}"

    pages = build_show_pages(message, description_limit=len(first_page))

    assert pages == (
        first_page,
        f"**Pings**\n{item_three}",
    )


def test_build_show_pages_splits_oversized_single_item_when_needed() -> None:
    pages = build_show_pages("**Pings**\n- " + ("x" * 25), description_limit=20)

    assert len(pages) == 3
    assert all(page.startswith("**Pings**\n") for page in pages)
    assert all(len(page) <= 20 for page in pages)


def test_show_pagination_view_sets_footer_and_button_states() -> None:
    detail = "x" * 2100
    result = DiscordCommandResult(
        title="Configuration Overview",
        message=f"**Pings**\n- one\n  {detail}\n- two\n  {detail}\n- three\n  {detail}",
        style=DiscordResultStyle.INFO,
        ephemeral=True,
    )

    view = ShowPaginationView(owner_id=200, result=result)
    view._page_index = 0
    view._sync_button_states()
    embed = view.render_embed()
    previous_button = _find_button(view, "Previous")
    next_button = _find_button(view, "Next")

    assert embed.footer.text == "Page 1/3"
    assert previous_button.disabled is True
    assert next_button.disabled is False
