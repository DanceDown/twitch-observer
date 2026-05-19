# Discord Setup

This document defines Discord platform requirements and runtime behavior.

Command syntax and parameters are documented in
[commands_reference.md](commands_reference.md).

## Scope

This document covers:

- Discord application and bot setup
- required scopes and permissions
- context model (channel/thread/DM)
- response visibility and embed behavior

It does not duplicate command parameter details.

## Required Discord configuration

- one Discord application
- the bot user belonging to that application
- bot token (`DISCORD_BOT_TOKEN`)
- application ID (`DISCORD_APPLICATION_ID`)
- installation scopes:
  - `bot`
  - `applications.commands`

The bot uses Discord application commands as root launchers and does not
require privileged message-content intents.

## Recommended channel permissions

- View Channel
- Send Messages
- Use Application Commands
- Embed Links

Thread usage requires access to those threads.

## Context model

Each Discord channel, thread, or DM is a separate configuration root.

That mapping is persisted in `thread.discord_channel_id`, which is unique per
context.

## Entrypoint and service boundary

The Discord entrypoint handles transport only:

1. receive interaction
2. normalize request data
3. call one direct service method
4. receive `DiscordCommandResult`
5. render embed response

Business logic stays in services and repository-backed workflows.

For event names and payload families, see [events.md](events.md).

## Response visibility model

- successful command results are visible in the active Discord context
- validation, permission, and lookup failures are normally ephemeral
- command results and tracking notifications are embeds

## Embed color model

Semantic result colors:

- success: green
- error: red
- info: blue

Tracking embed color inheritance:

1. pattern color
2. tracked channel color
3. Discord context color
4. Twitch author color
5. fallback gray

## Twitch validation dependencies

User-provided Twitch channel and user logins are validated through Helix.

Required credentials:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

Linked user tokens are used for Twitch chat writes and write-adjacent flows.
