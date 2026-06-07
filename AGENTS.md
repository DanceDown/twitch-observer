# AGENTS Notes

## Project Shape

- Entry point and dependency wiring live in `src/main.py`.
- Runtime flow is direct-call based: entrypoints normalize typed DTOs, services handle business logic, repositories persist state, and background workers trigger explicit orchestrators.
- `src/entrypoints/discord` contains Discord slash-command, modal, and UI integration.
- `src/entrypoints/twitch_irc` contains Twitch chat intake and IRC event parsing.
- `src/gateways` contains Helix-facing API clients and other external integrations.
- `src/services` contains application logic and orchestration.
- `src/services/patterns` and `src/services/replies` split the larger runtime services by responsibility.
- `src/events` is split by topic: `commands.py`, `discord_results.py`, `pattern_scopes.py`, `twitch_events.py`, and `ui_flow.py`.
- `src/database/records.py` contains record dataclasses, `src/database/repositories.py` contains interfaces, and `src/database/connection.py` contains PostgreSQL implementations.
- `docs/architecture.md` is the main architecture reference and should stay aligned with actual code flow.

## Architecture Rules

- Keep business logic in services, not in entrypoints or gateways.
- Prefer extending existing services and repositories over adding parallel abstractions.
- Touch as little code as possible for feature work; preserve existing wiring and boundaries.
- Reuse the current direct service composition, pipelines, and orchestrators instead of introducing new cross-layer shortcuts.
- Keep hot paths cheap, especially chat-message processing and pattern matching.

## Twitch User Metadata

- Twitch user data is cached persistently in `twitch_user_cache` and also in a small in-memory LRU inside `TwitchUserDirectoryService`.
- Incoming IRC messages should update cache entries from message metadata without triggering Helix lookups.
- Avoid live `Get Users` calls in the hot message path unless correctness absolutely requires it.
- Fresh Helix lookups are acceptable for explicit user-driven commands such as `/channel`, `/user`, and `/write`.
- Profile image URLs are not available from IRC metadata; they require Helix data and should therefore be refreshed sparingly.
- Background metadata refresh uses one shared interval (`TWITCH_METADATA_REFRESH_INTERVAL_SECONDS`) and refreshes the persistent cache in batches. There is no per-row refresh timestamp anymore.

## Live State and Auto-Replies

- Tracked channel live/offline state is persisted on `channel.is_live` rather than fetched per message.
- Tracked channels are monitored globally through `TwitchLiveMonitorService` with app-token Helix `Get Streams` polling.
- `/live` and `/offline` only configure follow-up behavior for tracked channel events inside one Discord context.
- External source-driven triggers should use the `adapter_event` plus `adapter_event_action` model.
- Linked Twitch accounts must only be used for Twitch writes and write-adjacent token validation.
- Pattern replies and external event actions are separate concepts; avoid forcing external event actions into pattern storage.
- External event auto-replies never support `reply_as_reply` because they do not originate from a source chat message.
- Keep live/offline side effects inside the existing `LiveStateChangeOrchestrator` flow so future integrations can plug into the same runtime path without bypassing services.

## Docs

- Project documentation should be written in English.
- Keep docs focused on actual runtime behavior, tradeoffs, and operational guidance.
- Avoid overlapping documentation; prefer one canonical document per topic.
- `docs/architecture.md` is the main runtime overview, `docs/database.md` is the schema guide, and `docs/commands_reference.md` is the user-facing command surface.
- German user-facing text must always use proper German characters: write `ä`, `ö`, `ü`, and `ß`; never replace them with `ae`, `oe`, `ue`, or `ss`.

## Localization Rules

- Jeglicher Text und Formatierungen müssen in den Lang-Files definiert sein.
- Jedes Discord Embed hat seinen eigenen Eintrag im Lang-File.
- Variablen dürfen nie geteilt werden, auch keine Listen; sie müssen für jedes Embed neu definiert sein.
- Variablen müssen zu 100% dynamisch sein. Wenn es nur wenige feste Optionen gibt, müssen diese als weitere Variablen im selben Scope definiert sein.
- Text-Builder sollen nur View-Daten und optionale Fragmente vorbereiten. Die endgültige Textstruktur muss aus dem Localizer und den Lang-Files kommen, nicht aus inline zusammengesetzter Prosa im Code.
- Optionale Textteile sollen über Lang-Variablen und Localizer-Interpolation gesteuert werden, nicht über hartcodierte Satzbausteine.
- Aktionen sind immer getrennt zu behandeln. `added`, `removed` und `updated` haben jeweils eigene Einträge und teilen sich niemals denselben.

## Communication

- use easy language when communicating with the user
- don't overcomplicate things
- don't overuse technical terms
- keep yourself concise

## Testing

- Prefer targeted tests for the touched flow before broader runs.
- Docker-based test execution is available and is the preferred integration test path in this repo.
- By default, always run tests, checks, and runtime validation through Docker (instead of host-local tooling) unless explicitly requested otherwise.
- Tests should validate behavior, side effects, persisted state, permissions, and triggered actions rather than exact user-facing wording.
- Avoid assertions that depend on 1:1 response text, embed titles, labels, or other easily changeable visual copy unless the text format itself is the feature under test.
- If schema changes are intentional and incompatible, call that out clearly and reset local persisted DB data only when explicitly required by the task.
