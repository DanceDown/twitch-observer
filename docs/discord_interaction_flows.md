# Discord Interaction Flows

This document summarizes which response paths Discord interactions can take and
which ones are useful for this bot.

It is based on the official Discord interaction documentation and the
`discord.py` interactions API:

- https://docs.discord.com/developers/interactions/receiving-and-responding
- https://docs.discord.com/developers/components/using-modal-components
- https://discordpy.readthedocs.io/en/stable/interactions/api.html

## Core Rules

### One interaction, one initial response

Every interaction has exactly one initial response.

In `discord.py` this is represented by `interaction.response`. Once that
response was used, `interaction.response.is_done()` becomes true and all further
messages must go through:

- `interaction.followup.send(...)`
- `interaction.edit_original_response(...)`
- `interaction.delete_original_response()`

### Initial response deadline

Discord requires an initial response within 3 seconds. After that, the token is
invalidated.

If more time is needed, the normal pattern is:

1. `await interaction.response.defer(...)`
2. do the work
3. send a follow-up or edit the original response

### Follow-up window

Interaction tokens remain valid for 15 minutes. During that time you can:

- send follow-up messages
- edit the original response
- delete the original response

## Interaction Sources

In practice this bot currently cares about four interaction sources:

- application commands
- message components
- modal submits
- autocomplete interactions

## 1. Application Command

Examples:

- `/join`
- `/channel add ...`
- `/ping add ...`
- `/account link`

### Valid initial responses

From a slash command you can:

- send a message
- defer
- send a modal
- launch an activity

In `discord.py` that means:

```python
await interaction.response.send_message("Done")
await interaction.response.defer(ephemeral=True)
await interaction.response.send_modal(MyModal())
await interaction.response.launch_activity()
```

### Good use cases

- `send_message`
  - use when the command already has all required parameters
  - example: `/ping remove id:4`
- `defer`
  - use when work takes longer than a moment
  - example: `/account link`
- `send_modal`
  - use when the command should collect more freeform data
  - example: `/leave` confirmation modal

### Typical continuation paths

#### Path A: command -> immediate result

```python
await interaction.response.send_message(embed=result_embed)
```

Best when the command is simple and complete.

#### Path B: command -> defer -> follow-up

```python
await interaction.response.defer(ephemeral=True)
result = await do_work()
await interaction.followup.send(embed=result_embed, ephemeral=True)
```

Best when validation or API calls need time.

#### Path C: command -> modal

```python
await interaction.response.send_modal(ChannelLeaveConfirmModal())
```

Best when the command should open a form instead of immediately doing work.

## 2. Message Component

Examples:

- button click
- string select choice
- user select choice
- channel select choice

### Valid initial responses

From a component interaction you can:

- send a message
- defer
- edit the original component message
- send a modal
- launch an activity

In `discord.py` that means:

```python
await interaction.response.send_message("Saved", ephemeral=True)
await interaction.response.defer()
await interaction.response.edit_message(embed=updated_embed, view=None)
await interaction.response.send_modal(EditPatternModal())
```

### Good use cases

- `edit_message`
  - update the original control message
  - example: a "Next Page" button on a paginated `/show`
- `send_modal`
  - open a second-step form from a button
  - example: click `Edit Pattern` -> modal opens
- `send_message`
  - send a new ephemeral result without touching the original message
  - example: click `Delete` -> show a warning response

### Typical continuation paths

#### Path A: component -> update same message

```python
await interaction.response.edit_message(embed=new_embed, view=new_view)
```

Best for paginators, selectors, toggles, and compact control panels.

#### Path B: component -> modal

```python
await interaction.response.send_modal(EditReplyModal())
```

Best for "click button first, then fill form".

#### Path C: component -> defer update -> later edit

```python
await interaction.response.defer()
result = await load_page()
await interaction.edit_original_response(embed=result_embed, view=result_view)
```

Best when the control message itself should change, but loading takes time.

## 3. Modal Submit

Examples:

- user confirms `/leave`
- user submits a complex pattern form

### Valid initial responses

From a modal submit you can:

- send a message
- defer
- edit a message
- launch an activity

In `discord.py` that means:

```python
await interaction.response.send_message(embed=result_embed, ephemeral=True)
await interaction.response.defer(ephemeral=True)
await interaction.response.edit_message(embed=updated_embed, view=None)
```

### Important limitation

A modal submit cannot directly respond with another modal.

That is the important Discord rule that caused the earlier errors in this
project:

- `command -> modal` is valid
- `component -> modal` is valid
- `modal submit -> another modal` is not valid

If you need a multi-step flow after a modal, the usual workaround is:

1. modal submit
2. send a message with buttons/selects
3. user clicks a button/select
4. that new component interaction opens the next modal

### Good use cases

- `send_message`
  - submit the form and show the result immediately
- `defer`
  - modal data is valid, but the actual work takes time
- `edit_message`
  - only useful when the modal came from a component-driven flow and the
    original message should be updated

## 4. Autocomplete Interaction

Examples:

- suggesting IDs while typing `/reply remove id:`
- suggesting tracked Twitch channels while typing `/write channel_name:`

### Valid initial response

Autocomplete interactions only return autocomplete choices.

In `discord.py`:

```python
await interaction.response.autocomplete(
    [
        app_commands.Choice(name="Pattern #4", value="4"),
        app_commands.Choice(name="Pattern #7", value="7"),
    ]
)
```

This interaction type is only for suggestions while the user types. It cannot
send messages or modals.

## Follow-Ups and Original Responses

After the initial response you still have a lot of control.

### Send a follow-up message

```python
await interaction.followup.send(embed=embed, ephemeral=True)
```

Useful after:

- a defer
- a long-running account-link or API flow

### Edit the original response

```python
await interaction.edit_original_response(embed=embed, view=view)
```

Useful when:

- the initial response was a deferred thinking response
- you want to replace the loading state with the final embed

### Delete the original response

```python
await interaction.delete_original_response()
```

Useful for:

- temporary ephemeral status messages
- component flows where the control message should disappear afterwards

## What Is Best For UX?

### Best for quick actions

Use a direct command result.

Example:

```text
/reply remove id:5
```

This should usually become:

- command -> immediate embed result

### Best for forms

Use command -> modal.

Example:

```text
/leave
```

Then:

- open confirmation modal
- modal submit -> final embed result

### Best for multi-step flows

Use command -> message with controls -> modal.

Example:

1. `/show patterns`
2. show paginated embed with a select menu
3. user selects one pattern
4. click `Edit`
5. button opens modal

This is usually more flexible than trying to force everything into one command
or one modal.

### Best when a process takes time

Use defer.

Example:

```python
await interaction.response.defer(ephemeral=True)
result = await start_device_flow()
await interaction.followup.send(embed=result_embed, ephemeral=True)
```

## Modal Structure Notes

Discord modals currently allow 1 to 5 top-level components.

The current Discord docs also show that select menus in modals must be wrapped
inside `Label` components.

That matters because:

- not every UI component is allowed as a top-level modal component
- some component types that exist in the library are not valid in every payload
  position

In short:

- `discord.py` can expose more UI classes than a specific Discord payload
  position allows
- always check the official Discord modal docs when something serializes but
  Discord rejects the payload

## Practical Design Recommendations For This Bot

### Good candidates for direct command responses

- `/ping remove id:4`
- `/ping disable id:2`
- `/reply enable id:7`
- `/on`
- `/off`

### Good candidates for command -> modal

- `/join`
- `/leave`
- `/account link` only if you later want to collect optional preferences

### Good candidates for command -> component -> modal

- `/show patterns`
- `/show replies`
- `/show permissions`

Reason:

- list first
- let the user choose an item
- then open edit/delete modal from that selection

### Good candidates for autocomplete

- pattern IDs
- reply IDs
- tracked Twitch channel names
- Discord users for permission changes

## Short Decision Guide

If the user already knows the exact target and only one small action is needed:

- use a command with parameters

If the user needs to type or review several fields:

- use a modal

If the user first needs to choose one item from a list:

- use a message with components

If the action needs more than 3 seconds:

- defer first
