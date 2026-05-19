# Architecture

This is the main runtime reference for the Twitch Observer.

## Layers

- Entrypoints
  - start runtime flow from Discord, Twitch IRC, or background workers
  - normalize external payloads
  - call one direct service, pipeline, or orchestrator
  - render transport-specific results
- Gateways
  - talk to external systems such as Twitch Helix
  - expose narrow integration contracts
- Services
  - own business logic
  - coordinate repositories and side effects through direct calls
- Pipelines and orchestrators
  - run explicit ordered multi-step flows
- Repositories
  - persist configuration, cache, and runtime state in PostgreSQL
- Localization
  - loads `lang/*.json` once at startup and resolves per-thread language keys

## Main inputs

- Discord
  - root command launchers, selects, modals, and buttons
- Twitch IRC
  - public chat intake
- Twitch Helix
  - validation, metadata, live-state polling, and chat writes

## Core runtime flows

### Chat message flow

1. `TwitchIRCEntrypoint` receives a Twitch `PRIVMSG`.
2. It normalizes the line into `TwitchChatMessageEvent`.
3. It forwards that DTO into `ChatMessageProcessingService`.
4. The chat pipeline runs, in order:
   - `MessageIngestService`
   - `TwitchUserDirectoryIngestService`
   - `PatternTrackingService`
   - `AutoReplyService`

### Live-state flow

1. `TwitchLiveMonitorService` periodically polls Helix `Get Streams` for all tracked channels.
2. It compares the result with persisted `channel.is_live`.
3. First-seen state is stored silently.
4. Actual transitions are forwarded directly to `LiveStateChangeOrchestrator`.
5. The orchestrator runs, in order:
   - `ChannelLiveStatePersistenceService`
   - `ChannelEventNotificationService`
   - `ChannelEventAutoReplyService`

### Command flow

1. A Discord command is dispatched from the Discord entrypoint.
2. The Discord entrypoint normalizes interaction data into one typed request DTO.
3. It calls one direct application service.
4. The service validates permissions and inputs, updates repositories, and returns a `DiscordCommandResult`.
5. The Discord entrypoint renders the result using the language stored on the
   active thread/context.

Pattern and reply entries use:

- a stable persisted internal pattern identifier for storage and relations
- a dense per-thread display number computed only when rendering UI or `/show`

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

## Persistence runtime

`PostgresDatabase` uses a small synchronous connection pool with:

- a hard cap on total active plus idle connections
- blocking acquire semantics
- a configurable acquire timeout that raises an internal technical failure when exhausted

This keeps repository access bounded even though the app still uses synchronous
PostgreSQL drivers.

## Implementation notes

- `src/bootstrap/application.py`
  - dependency wiring and lifecycle
- `src/main.py`
  - thin process entrypoint
- `src/entrypoints/`
  - runtime entrypoint exports for Discord and Twitch IRC
- `src/gateways/`
  - external integration exports
- `src/database/records.py`
  - shared persistence dataclasses
- `src/database/repositories.py`
  - repository interfaces used by services and tests
- `src/database/postgres/`
  - PostgreSQL pool and repository implementations split by persistence responsibility
- `src/entrypoints/discord/dispatch/`
  - typed per-domain direct call helpers used by Discord entrypoints and UI
- `src/entrypoints/discord/ui/patterns/`
  - split guided ping UI flow
- `src/services/chat_pipeline.py`
  - ordered Twitch chat processing pipeline
- `src/services/live_state_orchestrator.py`
  - ordered live/offline side effects
- `src/services/patterns/`
  - split pattern command, show, and tracking services
- `src/services/replies/`
  - split reply command, pattern auto-reply, and channel-event auto-reply services
- `src/services/account_service.py`
  - account command handling for link/unlink/show flows
- `src/services/account_polling_service.py`
  - background polling and completion of pending Twitch device-code logins
- `src/services/channel_live_state_service.py`
  - tracked channel event configuration commands
- `src/services/channel_event_notification_service.py`
  - live-state persistence and Discord notification fan-out
- `src/services/twitch_runtime.py`
  - shared Twitch runtime helpers and constants
- `src/services/twitch_live_monitor_service.py`
  - app-token-based live-state polling
- `src/services/twitch_user_directory_service.py`
  - persistent Twitch user cache

