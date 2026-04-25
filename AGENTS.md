# AGENTS Notes

## Project Shape

- Entry point and dependency wiring live in `src/main.py`.
- Runtime flow is event-driven: adapters publish domain events, services handle business logic, repositories persist state.
- `src/adapters/discord` contains Discord slash-command, modal, and UI integration.
- `src/adapters/twitch_irc` contains Twitch chat intake and IRC event parsing.
- `src/adapters/twitch_api` contains Helix-facing API clients.
- `src/services` contains application logic and orchestration.
- `src/services/patterns` and `src/services/replies` split the larger runtime services by responsibility.
- `src/database/records.py` contains record dataclasses, `src/database/repositories.py` contains interfaces, and `src/database/connection.py` contains PostgreSQL implementations.
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
- Tracked channels are monitored globally through `TwitchLiveMonitorService` with app-token Helix `Get Streams` polling.
- `/live` and `/offline` only configure follow-up behavior for tracked channel events inside one Discord context.
- External source-driven triggers should use the `adapter_event` plus `adapter_event_action` model.
- Linked Twitch accounts must only be used for Twitch writes and write-adjacent token validation.
- Pattern replies and external event actions are separate concepts; avoid forcing external event actions into pattern storage.
- External event auto-replies never support `reply_as_reply` because they do not originate from a source chat message.
- Keep live/offline side effects event-driven so future Twitch, Discord, or other adapters can publish into the same flow.

## Docs

- Project documentation should be written in English.
- Keep docs focused on actual runtime behavior, tradeoffs, and operational guidance.
- Avoid overlapping documentation; prefer one canonical document per topic.
- `docs/architecture.md` is the main runtime overview, `docs/database.md` is the schema guide, and `docs/commands_reference.md` is the user-facing command surface.

## Testing

- Prefer targeted tests for the touched flow before broader runs.
- Docker-based test execution is available and is the preferred integration test path in this repo.
- Tests should validate behavior, side effects, persisted state, permissions, and triggered actions rather than exact user-facing wording.
- Avoid assertions that depend on 1:1 response text, embed titles, labels, or other easily changeable visual copy unless the text format itself is the feature under test.
- If schema changes are intentional and incompatible, call that out clearly and reset local persisted DB data only when explicitly required by the task.
