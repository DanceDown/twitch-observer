# Discord Twitch Observer

This project connects Discord channels, threads, or DMs with Twitch chat.

Users configure the observer through Discord slash commands. The application
stores configuration in PostgreSQL, reads Twitch chat through anonymous Twitch
IRC, polls Twitch live state through the Helix API, forwards matching messages
to Discord, and can optionally send Twitch auto-replies through a linked Twitch
account.

## Feature Scope

- track multiple Twitch channels per Discord context
- add ping and regex rules through Discord commands
- forward matching Twitch messages to Discord embeds
- attach Twitch auto-replies to patterns or configured live/offline events
- notify Discord when tracked channels go live or offline
- link a Twitch account through the Twitch Device Code Flow
- keep separate configuration per Discord channel, thread, or DM

## Runtime overview

The runtime has four main parts:

1. PostgreSQL
   - stores configuration, observed messages, cached Twitch user metadata, and persisted channel live state
2. Python application server
   - hosts the Discord bot
   - connects to anonymous Twitch IRC for read-only chat intake
   - calls the Twitch Helix API for validation, metadata lookup, live-state polling, and sending replies
3. Discord users
   - configure the observer through slash commands
4. Twitch application credentials
   - back app-token Helix access for validation and background live monitoring

## Startup

### Requirements

- Python 3.13
- PostgreSQL
- a Discord application with bot token
- a Twitch application with `client_id` and `client_secret`

### Minimal environment

At minimum the application needs:

- PostgreSQL connection settings
- `DISCORD_BOT_TOKEN`
- `DISCORD_APPLICATION_ID`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

### Run locally

1. start PostgreSQL
2. apply [src/database/schema.sql](src/database/schema.sql)
3. fill `.env`
4. start the app through `src/main.py` or Docker Compose

## Feature Notes

- pings are matched as whole-word searches
- regexes use Python regular expressions
- `case_sensitive` affects both modes
- pattern priority decides which matching rule wins first
- patterns can be edited after creation
- per-user permissions can delegate configuration access inside one Discord context
- linked users can manually send Twitch messages and replies from Discord
- tracked channels are live-monitored globally through app-token Helix polling
- `/live` configures live and offline notifications, not the monitoring itself
- color inheritance for Discord embeds is:
  - pattern color
  - source channel color
  - Discord thread color
  - Twitch author color
  - gray fallback

## Key docs

- [docs/README.md](docs/README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/database.md](docs/database.md)
- [docs/commands_reference.md](docs/commands_reference.md)
- [docs/events.md](docs/events.md)
- [docs/discord.md](docs/discord.md)
- [docs/discord_interaction_flows.md](docs/discord_interaction_flows.md)
- [docs/twitch_irc.md](docs/twitch_irc.md)
- [docs/adding_commands.md](docs/adding_commands.md)
- [docs/development.md](docs/development.md)
- [docs/testing_playbook.md](docs/testing_playbook.md)
