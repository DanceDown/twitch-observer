# discord.py UI Overview

This is a compact overview of the most relevant `discord.py` interaction UI
features for this project. Each entry uses a small example instead of a raw
parameter list.

## Modal

Use a modal when the bot should ask the user for structured input in a dialog.

Example:

- `/ping add ...` exposes focused slash-command parameters instead of requiring a long free-form text command.

## TextInput

Use a text input for free-form values.

Example:

- `Regex Pattern: ^h[a4]llo$`
- `Embed Color: #ff9ce5`

## Select

Use a string select when the user should choose one or more predefined textual
options.

Example:

- `Action: Add / Remove`
- `Show: Channels / Pings / Regex`

In `discord.py`, the constructible string-select class is `discord.ui.Select`.

## RadioGroup

Use a radio group when exactly one option from a small set should be chosen.

Example:

- `Subscriber Scope: Everyone / Subscribers Only / Non-Subscribers Only`
- `Live Status: Both / Only Online / Only Offline`

## CheckboxGroup

Use a checkbox group when zero or more flags should be toggled independently.

Example:

- `Treat as Regex`
- `Case Sensitive`
- `Start Disabled`

## Label

Use a label to place a heading above a non-text modal component.

Example:

- a `Select` with the heading `Action`
- a `RadioGroup` with the heading `Subscriber Scope`

## Interaction Response

Use the interaction response for the first reply to a slash command or modal
submit.

Example:

- open a modal with `interaction.response.send_modal(...)`
- return the final result embed with `interaction.response.send_message(...)`

## Follow-up Messages

Use a follow-up message only after the original interaction response was already
used.

Example:

- if a handler already opened a modal or sent a message, later replies can use
  `interaction.followup.send(...)`

## CommandTree

Use the command tree to register slash commands.

Example:

- register `/channel`, `/ping`, `/regex`, and `/show`

## Modal composition

Modals can be composed dynamically before they are sent.

Example:

- create a modal
- `add_item(...)` for the fields you want
- optionally `remove_item(...)` or `clear_items()` before sending it

Important limit:

- once a modal is already open on the Discord client, it cannot be changed live
- a modal submit cannot directly open another modal as its response
- a modal can only hold up to 5 child items

That is why the current project prefers focused slash-command parameters for
most v1 flows and would only use modals for tightly scoped follow-up input.
