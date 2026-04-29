# Architecture

This is the main runtime reference for the Twitch Observer.

## Layers

- Adapters
  - translate external systems into internal events
  - render results back to Discord or Twitch
- Services
  - own business logic
  - react to events
  - coordinate repositories and side effects
- Repositories
  - persist configuration, cache, and runtime state in PostgreSQL
- Localization
  - loads `lang/*.json` once at startup and resolves per-thread language keys
- Event bus
  - keeps adapters and services decoupled

## Main inputs

- Discord
  - slash commands, modals, and buttons
- Twitch IRC
  - public chat intake
- Twitch Helix
  - validation, metadata, live-state polling, and chat writes

## Core runtime flows

### Chat message flow

1. `AnonymousTwitchIRCAdapter` receives a Twitch `PRIVMSG`.
2. It publishes `TwitchChatMessageEvent`.
3. `MessageIngestService` stores the message.
4. `TwitchUserDirectoryIngestService` updates `twitch_user_cache` from IRC metadata.
5. `PatternTrackingService` evaluates message-driven patterns.
6. `AutoReplyService` evaluates pattern-bound Twitch auto-replies.

### Live-state flow

1. `TwitchLiveMonitorService` periodically polls Helix `Get Streams` for all tracked channels.
2. It compares the result with persisted `channel.is_live`.
3. First-seen state is stored silently.
4. Actual transitions publish `TwitchChannelLiveStateChangedEvent`.
5. `ChannelLiveStatePersistenceService` persists the new state.
6. `ChannelEventNotificationService` sends Discord notifications for configured live/offline triggers managed through `/live`.
7. `ChannelEventAutoReplyService` sends Twitch messages for configured live/offline event actions.

### Command flow

1. A Discord command is dispatched from the Discord adapter.
2. The adapter publishes one typed command event.
3. The matching service validates permissions and inputs.
4. The service updates repositories and returns a `DiscordCommandResult`.
5. The Discord adapter renders the result using the language stored on the
   active thread/context.

## Key design decisions

### Tracked channels are infrastructure

A row in `channel` means:

- read this Twitch chat on IRC
- poll this channel for live/offline state
- allow patterns to scope to it

It does not mean:

- notify on live/offline automatically

Notifications and event-driven follow-up actions are configured separately through
`adapter_event` and `adapter_event_action`.

### Live monitoring is app-owned, not user-owned

Background live/offline monitoring must not depend on whichever user happened to
link a Twitch account in one Discord context.

The app therefore uses Helix `Get Streams` with the Twitch application
credentials for live-state polling.

That keeps ownership correct:

- linked user accounts are only used for Twitch writes
- live/offline monitoring works even when no user account is linked

### Patterns and external events stay separate

- `pattern` + `reply` are for message-driven behavior
- `adapter_event` + `adapter_event_action` are for source-driven behavior

This avoids forcing live/offline events into the pattern model.

## Caching model

### Twitch users

`TwitchUserDirectoryService` is the central Twitch user lookup layer.

It uses:

- PostgreSQL cache in `twitch_user_cache`
- a small in-memory LRU
- Helix fallback only when needed

IRC metadata updates login and display-name information without a Helix call.
Profile images require Helix.

### Live state

`channel.is_live` is the single persisted live/offline source of truth for:

- pattern `offline_state` filtering
- `/show`
- live/offline notifications
- event-driven Twitch auto-replies

The message hot path never calls `Get Streams`.

## Twitch auth model

- App credentials
  - user lookup validation
  - live-state polling
- Linked user credentials
  - `/write`
  - pattern auto-replies
  - live/offline event auto-replies

## Implementation notes

- `src/main.py`
  - dependency wiring and lifecycle
- `src/database/records.py`
  - shared persistence dataclasses
- `src/database/repositories.py`
  - repository interfaces used by services and tests
- `src/database/connection.py`
  - PostgreSQL schema bootstrapping and repository implementations
- `src/services/patterns/`
  - split pattern command, show, and tracking services
- `src/services/replies/`
  - split reply command, pattern auto-reply, and channel-event auto-reply services
- `src/services/twitch_runtime.py`
  - shared Twitch runtime helpers and constants
- `src/services/twitch_live_monitor_service.py`
  - app-token-based live-state polling
- `src/services/twitch_user_directory_service.py`
  - persistent Twitch user cache
