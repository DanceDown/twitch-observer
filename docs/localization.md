# Runtime Localization

## Goal

Runtime-visible Discord text and formatting belong in `lang/*.json`.

This includes:

- command result titles and messages
- modal titles, labels, placeholders, and descriptions
- section wrappers, bullet prefixes, separators, and inline-code fragments
- reusable link and mention fragments

This does not include:

- slash-command metadata and choice labels declared at registration time
- logs
- internal keys, enum values, or action tokens

## Placeholder Modes

The `Localizer` supports three explicit placeholder modes:

- `{NAME}`: escaped Discord text
- `{RAW:NAME}`: inserted as-is
- `{CODE:NAME}`: inserted for inline-code contexts; runtime backticks are normalized before rendering

Use `{RAW:...}` only for fragments that are already safe and intentionally formatted, such as:

- rendered bullet lists
- rendered Twitch profile links
- Discord mentions
- full section bodies

## Reusable Lists

Reusable list and wrapper formats live in the language files under `common.lists` and `common.fragments`.

Current shared building blocks include:

- `common.fragments.twitch_code_link`
- `common.fragments.twitch_link`
- `common.fragments.section`
- `common.fragments.inline_code`
- `common.fragments.discord_user_mention`
- `common.lists.raw_lines`
- `common.lists.bullets`
- `common.lists.indented_bullets`
- `common.lists.comma_raw`
- `common.lists.section_breaks`

Use `Localizer.format_list(...)` instead of building runtime-visible lists with Python string concatenation.

## Guardrails

- Do not add new runtime copy directly in entrypoints or services when it can live in a language file.
- Prefer composing localized fragments over hand-built Markdown.
- When a runtime value is intended to stay clickable, pass it through a `{RAW:...}` placeholder into a language-file template that owns the surrounding formatting.
