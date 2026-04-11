# Discord Setup

This document describes the current Discord bot requirements and the current
slash-command UX used by the application.

The canonical list of all currently supported commands and parameters lives in
[commands_reference.md](commands_reference.md).

## What the bot currently needs

For the current implementation, the application needs:

- a Discord application
- the bot user that belongs to that application
- the bot token
- installation with the scopes `bot` and `applications.commands`

At the moment, the bot does not need privileged intents such as
`MESSAGE_CONTENT`. The current feature set is based on slash commands, not on
free-form message parsing.

## Recommended permissions

For the current slash-command setup, the bot should at least be able to:

- view the channel it is used in
- send messages
- use application commands
- embed links

If the bot should work in threads, it also needs access to those threads.

## DM and guild usage

The same command flow works in both places:

- DMs with the bot
- server channels and threads where the bot has access

Internally, every Discord channel is treated as one configuration root. That
includes:

- normal guild channels
- threads
- DMs

This is why `thread.discord_channel_id` is unique in the database.

## Why the UX is command-first

The current Discord UX uses focused slash commands and subcommands.

This gives two concrete UX benefits:

- the user sees only the parameters that belong to the chosen action
- successful results can go back as the direct interaction response

Example:

- `/ping add ...` shows add-related options such as filters and scope
- `/ping remove ...` only asks for the stable `id`

## Current commands

The full current command surface, with all parameters and examples, is
documented in [commands_reference.md](commands_reference.md).

The short version is:

- lifecycle:
  - `/join`
  - `/leave`
  - `/on`
  - `/off`
  - `/color`
- tracked Twitch channels:
  - `/channel add`
  - `/channel remove`
  - `/channel color`
- tracking rules:
  - `/ping add`
  - `/ping remove`
  - `/ping disable`
  - `/ping enable`
  - `/ping edit`
- linked Twitch account:
  - `/account link`
  - `/account unlink`
  - `/account show`
- auto-replies:
  - `/reply add`
  - `/reply remove`
  - `/reply disable`
  - `/reply enable`
- manual Twitch sending:
  - `/write`
- permission delegation:
  - `/permission grant`
  - `/permission revoke`
  - `/permission clear`
- inspection:
  - `/show`

## Internal event flow

The Discord adapter does not contain business logic.

Instead it:

1. receives a slash command
2. collects normalized command values
3. publishes an event
4. waits for the service result
5. sends the result embed

Examples:

- `/join`, `/leave`, `/on`, `/off` -> `discord.thread.requested`
- `/channel add` or `/channel remove` -> `discord.channel.requested`
- `/ping add`, `/ping remove`, `/ping enable`, `/ping disable` -> `discord.pattern.requested`
- `/ping edit` -> `discord.pattern.edit.requested`
- `/account link`, `/account unlink`, `/account show` -> `discord.account.requested`
- `/reply add`, `/reply remove`, `/reply disable`, `/reply enable` -> `discord.reply.requested`
- `/write` -> `discord.write.requested`
- `/permission ...` -> `discord.permission.requested`
- `/show` -> `discord.show.requested`

## Visibility rules

The current response model is:

- success responses are visible in the current Discord context
- validation and permission errors are ephemeral
- all responses are embeds

Tracking notifications are also always embeds.

## Embed styling

Discord responses use a centralized color palette so the whole application stays
visually consistent.

Current semantic colors:

- success: green
- error: red
- info: blue

The helper currently lives in `src/utils/discord_embeds.py`.

## Why Twitch validation needs API credentials

The Discord flow does not trust raw user input blindly. Before storing Twitch
channel or user scopes, the service resolves the provided logins through the
Twitch API.

That avoids invalid rows such as typos or channels that do not exist.

For this validation, the application currently needs:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

These are used only for the server-side app-token flow against Twitch.

For auto-replies, the linked user token is validated separately and later used
with Twitch's official Send Chat Message API.
