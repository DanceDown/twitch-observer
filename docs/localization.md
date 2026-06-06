# Runtime Localization

## Goal

Runtime-visible Discord text and formatting belong in `lang/*.json`.

This includes:

- command result titles and messages
- modal titles, labels, placeholders, and descriptions
- section wrappers, bullet prefixes, separators, and inline-code fragments
- mentions, timestamps, and Twitch profile links

This does not include:

- slash-command metadata and choice labels declared at registration time
- logs
- internal keys, enum values, or action tokens

## Sources

The runtime now sends structured source objects to the localizer instead of flat placeholder maps.

Typical namespaces are:

- `thread`
- `view`
- `event`
- `requester`
- `account`

Use dot-path placeholders in the language files:

- `{view.display_name}`
- `{CODE:view.id}`
- `{RAW:view.section_body}`
- `{MENTION:view.user_id}`
- `{TIMESTAMP:view.expires_at}`

For list rendering, use `item.*` inside `item_format`:

- `[`{CODE:item.display_name}`](https://www.twitch.tv/{RAW:item.login})`

## Placeholder Modes

The `Localizer` supports these placeholder modes:

- `{name}`: escaped Discord text
- `{RAW:name}`: inserted as-is
- `{CODE:name}`: normalized for inline-code output
- `{MENTION:name}`: rendered as a Discord user mention
- `{TIMESTAMP:name}`: rendered from ISO timestamps with the per-language timestamp format

Use `{RAW:...}` only for fragments that are already safe and intentionally formatted, such as:

- rendered bullet lists
- rendered Twitch profile links
- full section bodies

## Placeholder Specs

Template entries may define `placeholders` metadata for one dot-path placeholder.

Supported formatter specs:

- `list`
- `lookup`
- `mention`
- `timestamp`
- `path`

Example:

```json
{
  "template": "{RAW:view.items}",
  "placeholders": {
    "view.items": {
      "list": {
        "item_format": "- {RAW:item}",
        "separator": "\n"
      }
    }
  }
}
```

`lookup` resolves one runtime value against localized labels. `path` lets one placeholder name read from another source path when needed.

## Guardrails

- Do not add new runtime copy directly in entrypoints or services when it can live in a language file.
- Prefer sending structured source objects over hand-built placeholder maps.
- Keep visible formatting decisions in the localizer and language catalogs.
- When a runtime value is intended to stay clickable, pass the raw data and let the language file own the Markdown wrapper.
