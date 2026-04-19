# AGENTS Notes

## Project Shape

- Entry point and dependency wiring live in `src/main.py`.
- Runtime flow is event-driven: adapters publish domain events, services handle business logic, repositories persist state.
- `src/adapters/discord` contains Discord slash-command, modal, and UI integration.
- `src/adapters/twitch_irc` contains Twitch chat intake and IRC event parsing.
- `src/adapters/twitch_api` contains Helix-facing API clients.
- `src/services` contains application logic and orchestration.
- `src/database` contains schema and PostgreSQL repositories.
- `docs/architecture.md` is the main architecture reference and should stay aligned with actual code flow.

## Architecture Rules

- Keep business logic in services, not in adapters.
- Prefer extending existing services and repositories over adding parallel abstractions.
- Touch as little code as possible for feature work; preserve existing wiring and boundaries.
- Reuse the event bus and current service composition instead of introducing direct cross-layer calls.
- Keep hot paths cheap, especially chat-message processing and pattern matching.

## Twitch User Metadata

- Twitch user data is cached persistently in `twitch_user_cache` and also in a small in-memory LRU inside `TwitchUserDirectoryService`.
- Incoming IRC messages should update cache entries from message metadata without triggering Helix lookups.
- Avoid live `Get Users` calls in the hot message path unless correctness absolutely requires it.
- Fresh Helix lookups are acceptable for explicit user-driven commands such as `/channel`, `/user`, and `/write`.
- Profile image URLs are not available from IRC metadata; they require Helix data and should therefore be refreshed sparingly.

## Live State and Auto-Replies

- Tracked channel live/offline state is persisted on `channel.is_live` rather than fetched per message.
- Manual `/live` and `/offline` commands should publish events and let services persist and react to them.
- Pattern replies and channel live/offline event replies are separate concepts; avoid forcing channel-event replies into pattern storage.
- Keep channel-event side effects event-driven so a future non-Discord live-state adapter can publish the same domain event.

## Docs

- Project documentation should be written in English.
- Keep docs focused on actual runtime behavior, tradeoffs, and operational guidance.
- When behavior changes materially, update the closest existing document instead of creating overlapping docs unless a dedicated flow document is clearly useful.

## Testing

- Prefer targeted tests for the touched flow before broader runs.
- Docker-based test execution is available and is the preferred integration test path in this repo.
- If schema changes are intentional and incompatible, call that out clearly and reset local persisted DB data only when explicitly required by the task.
