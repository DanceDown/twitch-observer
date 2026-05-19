# discord.py UI Overview

This document summarizes the UI primitives used by this project.

Interaction protocol rules (initial response, defer, follow-up lifecycle) are
documented in [discord_interaction_flows.md](discord_interaction_flows.md).

## Scope

This document covers component types and usage patterns.

Command-specific flows are split into focused modules under
`src/entrypoints/discord/ui/`. The ping flow, for example, lives under
`src/entrypoints/discord/ui/patterns/` instead of one monolithic file.

## Modal

Use a modal to collect structured multi-field input.

Examples:

- leave confirmation
- write-to-Twitch form
- ping/reply form steps

## TextInput

Use `discord.ui.TextInput` for free-form values.

Examples:

- pattern text or regex text
- embed color hex value
- Twitch message body

## Select

Use `discord.ui.Select` for predefined choices.

Examples:

- choose tracked channel
- choose an existing ping/reply entry
- choose action mode

## RadioGroup / CheckboxGroup

Use radio groups for exactly-one choices and checkbox groups for independent
flags.

Examples:

- stream-state filter (`both`, `online`, `offline`)
- match mode and case-sensitivity options

## Label

Use labels to title non-text modal controls so the form remains self-explanatory.

## CommandTree

Root Discord entrypoints are registered through `discord.app_commands.CommandTree`.
Those entrypoints then hand off to component-driven flows.

Registration remains split across the dedicated command modules under:

- `src/entrypoints/discord/commands/`

## UI ownership and safety

- forms are interaction-owner locked
- paginators are interaction-owner locked
- locked interactions return localized lock messages

## Modal composition constraints

- one modal supports up to five child items
- modal submit interactions cannot respond with another modal directly
- multi-step flows should use:
  - modal submit -> message with controls -> component interaction -> next modal

