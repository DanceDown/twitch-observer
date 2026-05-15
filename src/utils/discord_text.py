"""Discord-safe text helpers shared by localization and embed rendering."""

from __future__ import annotations

import re

URL_PATTERN = re.compile(r"https?://[^\s]+")
DISCORD_MARKDOWN_PATTERN = re.compile(r"([\\*_`~|>\[\]()])")
DISCORD_MENTION_PATTERN = re.compile(r"@(everyone|here|[!&]?\d{15,20})")


def normalize_discord_code_value(text: str) -> str:
    """Replace backticks in runtime values so inline-code templates stay intact."""
    return text.replace("`", "´")


def escape_discord_text(text: str) -> str:
    """Escape Discord markdown and mentions for display-only text fragments."""
    escaped_markdown = DISCORD_MARKDOWN_PATTERN.sub(r"\\\1", text)
    return DISCORD_MENTION_PATTERN.sub(lambda match: f"@\u200b{match.group(1)}", escaped_markdown)


def escape_discord_preserving_links(text: str) -> str:
    """Escape Discord formatting while keeping raw URLs clickable."""
    rendered: list[str] = []
    last_end = 0
    for match in URL_PATTERN.finditer(text):
        start, end = match.span()
        rendered.append(escape_discord_text(text[last_end:start]))
        rendered.append(match.group(0))
        last_end = end
    rendered.append(escape_discord_text(text[last_end:]))
    return "".join(rendered)
