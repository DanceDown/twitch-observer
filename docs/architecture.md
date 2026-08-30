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
- Runtime relays
  - own late-bound communication from services/workers back into runtime adapters
  - keep services unaware of concrete Discord or live-monitor instances
- Repositories
  - persist configuration, cache, and runtime state in PostgreSQL
- Localization
  - loads `lang/*.json` once at startup and resolves per-thread language keys
  - code should pass view data into the localizer; final text shape belongs in the lang files

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
3. It enqueues that DTO into `ChatMessageProcessingService`, so IRC reading
   and PING/PONG handling are not blocked by Discord, Twitch API, or database
   work.
4. Background chat workers run the pipeline, in order:
   - `MessageIngestService`
   - `TwitchUserDirectoryIngestService`
   - `ChatMessageReactionService`
5. `ChatMessageReactionService` evaluates matching once and then dispatches
   prepared matches to tracking or auto-reply handling.
6. `ChatMessageReactionService` reserves matched Discord threads before slow
   side effects such as metadata lookups or Twitch writes.
7. Tracking embeds are handed to `OrderedTrackingDeliveryService`, which keeps
   Discord delivery in IRC message order per Discord thread even though worker
   processing happens in parallel.

### Live-state flow

1. `TwitchLiveMonitorService` periodically polls Helix `Get Streams` for all tracked channels.
2. It compares the result with persisted `tracked_channel_state.is_live`.
3. First-seen state is stored silently.
4. Actual transitions are forwarded directly to `LiveStateChangeOrchestrator`.
5. The orchestrator runs, in order:
   - `ChannelLiveStatePersistenceService`
   - `ChannelEventAutoReplyService`
   - `ChannelEventNotificationService`
6. Runtime-side notifications go through small relays from
   `ApplicationRuntimeCoordinator`.

### Command flow

1. A Discord command is dispatched from the Discord entrypoint.
2. The Discord entrypoint normalizes interaction data into one typed request DTO.
3. It calls one direct application service.
4. The service validates permissions and inputs, updates repositories, and returns a `DiscordCommandResult`.
5. The Discord entrypoint renders the result using the language stored on the
   active thread/context.

Read-only Discord UI flows use `DiscordUIQueryBundle` query services instead of
reading repositories directly from the Discord adapter.

Pattern and reply entries use:

- a stable persisted internal pattern identifier for storage and relations
- a dense per-thread display number computed only when rendering UI or `/show`

### Support flow

1. `/support` calls `SupportCommandService` with the requester's Discord context.
2. The service validates configuration and creates an `open` ticket.
3. The Discord adapter posts the localized ticket embed and persistent button
   view in the configured support channel, then stores the support message ID.
4. `Reply` and `Close` first prepare the user-facing response and send it to the
   original Discord context.
5. Only after that delivery succeeds does the ticket move to `answered` or
   `closed`, and the support-channel message is edited without buttons.
6. `Show` reuses the existing `/show` section renderer for the original context
   while bypassing the normal thread-user permission check for support staff.

## Key design decisions

### Tracked channels are infrastructure

A row in `channel` means:

- read this Twitch chat on IRC
- poll this channel for live/offline state
- allow patterns to scope to it

The per-thread `channel` row owns subscription and presentation state such as
the optional color override. The app-owned live/offline state itself is stored
globally in `tracked_channel_state` and is joined back into `ChannelRecord`
reads when a thread needs it. Runtime channel discovery is still based on
`channel`, so missing `tracked_channel_state` rows do not make tracked channels
disappear from IRC or live monitoring.

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

### Runtime communication stays narrow

`ApplicationRuntimeCoordinator` owns small relays for:

- tracking embeds
- account-link results
- channel-event Discord results
- Discord presence updates
- tracked-channel wake-ups for the live monitor

Services receive only the relay they need, not the whole runtime adapter graph.

## Caching model

### Twitch users

`TwitchUserDirectoryService` is the central Twitch user lookup layer.

It uses:

- PostgreSQL cache in `twitch_user_cache`
- a small in-memory LRU
- Helix fallback only when needed

IRC metadata updates login and display-name information without a Helix call.
Repeated identical IRC metadata is skipped in memory to avoid writing the same
cache row for every chat message.
Parallel cache misses for the same user are deduplicated in-process so only one
Helix lookup runs per key at a time. Profile images still require Helix.

The persistent cache is also refreshed by `TwitchMetadataRefreshService` in
full batched passes on one shared interval
(`TWITCH_METADATA_REFRESH_INTERVAL_SECONDS`). The schema no longer stores a
separate per-row "last refresh" timestamp.

### Live state

`tracked_channel_state.is_live` is the single persisted live/offline source of truth for:

- pattern `offline_state` filtering
- `/show`
- live/offline notifications
- event-driven Twitch auto-replies

The message hot path never calls `Get Streams`.
Pattern tracking and pattern auto-reply notification embeds use cached Twitch
user metadata first. When visual metadata such as profile images is missing, the
chat worker may run a bounded Helix user lookup
(`TWITCH_CHAT_METADATA_LOOKUP_TIMEOUT_SECONDS`). A slow lookup delays only that
message's prepared Discord notification; other workers can continue, and the
ordered delivery queue preserves Discord message order per Discord thread.
Shared Helix refresh tasks are shielded from per-message lookup timeouts so a
timed-out worker does not cancel cache warming for later messages.

### Message write buffering

Twitch chat messages and thread-match markers are buffered by
`BatchedMessageRepository` and flushed frequently
(`TWITCH_MESSAGE_WRITE_FLUSH_INTERVAL_SECONDS`) or when the batch size is
reached. Runtime PostgreSQL disconnects requeue the pending writes in memory.
If PostgreSQL is already unavailable during final shutdown, the pending writes
are stored in `TWITCH_MESSAGE_WRITE_SPOOL_PATH` and replayed on the next start.

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

At startup, `build_core()` opens the pool, applies ordered SQL migrations from
`src/database/migrations/`, and only then wires repositories and services.

## Implementation notes

- `src/bootstrap/core.py`
  - persistence, localization, and Twitch bundle assembly
- `src/bootstrap/services.py`
  - application service, query-service, and relay assembly
- `src/bootstrap/runtime.py`
  - entrypoint and runtime worker assembly
- `src/bootstrap/models.py`
  - shared bootstrap dataclasses
- `src/main.py`
  - thin process entrypoint
- `src/events/commands.py`
  - typed command payloads for Discord-triggered service calls
- `src/events/discord_results.py`
  - typed Discord result models
- `src/events/pattern_scopes.py`
  - shared typed scope enums for patterns and filters
- `src/events/twitch_events.py`
  - normalized Twitch chat and live-state runtime payloads
- `src/events/ui_flow.py`
  - typed UI flow requests and decisions
- `src/entrypoints/`
  - runtime entrypoint exports for Discord and Twitch IRC
- `src/gateways/`
  - external integration exports
- `src/database/records.py`
  - shared persistence dataclasses
- `src/database/repositories.py`
  - repository interfaces used by services and tests
- `src/database/postgres/`
  - PostgreSQL pool, migration runner, and repository implementations split by persistence responsibility
- `src/entrypoints/discord/dispatch/`
  - typed per-domain direct call helpers used by Discord entrypoints and UI
- `src/entrypoints/discord/ui/patterns/`
  - split guided ping UI flow
- `src/entrypoints/discord/ui/support_ui.py`
  - support ticket buttons, reply modal, and support-side show modal
- `src/services/chat_pipeline.py`
  - ordered Twitch chat processing pipeline
- `src/services/tracking_delivery_queue.py`
  - ordered Discord tracking delivery after parallel chat processing
- `src/services/live_state_orchestrator.py`
  - ordered live/offline side effects
- `src/services/runtime_coordinator.py`
  - grouped late-bound runtime relays
- `src/services/patterns/`
  - split pattern command, show, and tracking services
- `src/services/show/`
  - focused `/show` section renderers plus tiny Localizer-first text helpers
- `src/services/support_command_service.py`
  - support ticket creation, status transitions, and support-side show access
- `src/services/replies/`
  - split reply command, pattern auto-reply, and channel-event auto-reply services
- `src/services/account_service.py`
  - account command handling for link/unlink/show flows
- `src/services/account_polling_service.py`
  - background polling and completion of pending Twitch device-code logins
- `src/services/account_support.py`
  - shared account-link formatting and notification contracts
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

