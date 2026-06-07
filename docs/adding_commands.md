# Adding Commands

This guide explains how to add a Discord feature as one vertical slice across
entrypoints, typed request DTOs, services, persistence, and tests.

## Scope

This document covers implementation workflow.  
Command behavior details belong in [commands_reference.md](commands_reference.md).

## Architecture boundaries

- `src/entrypoints/discord/commands/*`
  - root command registration and interaction entry points
- `src/entrypoints/discord/ui/*`
  - modals, menus, and component-driven forms
- `src/entrypoints/discord/dispatch/*`
  - typed per-domain direct call helpers
- `src/events/commands.py`
  - typed request DTOs for Discord-triggered service calls
- `src/events/ui_flow.py`
  - typed UI flow requests and decisions
- `src/events/twitch_events.py`
  - normalized Twitch runtime payloads
- `src/events/pattern_scopes.py`
  - shared typed scope enums
- `src/services/*`
  - business logic and orchestration
- `src/database/*`
  - schema, repository contracts, and implementations
- `src/bootstrap/services.py`
  - application service and query-service assembly
- `src/bootstrap/runtime.py`
  - runtime worker and entrypoint assembly

## Implementation workflow

1. Define domain behavior and data ownership.
2. Add or extend persisted schema when needed.
3. Add/extend record and repository contracts.
4. Add a typed request DTO or runtime DTO when useful.
5. Add or extend a direct dispatch helper.
6. Implement service logic with a direct method returning `DiscordCommandResult`.
7. Add root command registration and UI interaction entry points.
8. Wire service/repository in the matching bootstrap module (`core.py`, `services.py`, or `runtime.py`).
9. Add tests for service behavior and affected flows.
10. Update docs for command surface and operational behavior.

## Step 1: Typed request contract

Add the DTO in the themed module that matches its responsibility:

- `src/events/commands.py` for Discord command payloads
- `src/events/ui_flow.py` for UI-flow requests/decisions
- `src/events/twitch_events.py` for normalized runtime Twitch payloads

The DTO should contain:

- context identity (`discord_channel_id`, `requester_id`)
- normalized command data

Rules:

- payload fields must be normalized and explicit
- avoid passing raw Discord objects into services

## Step 2: Dispatch helper

Add a helper in the matching module under `src/entrypoints/discord/dispatch/` that:

1. creates the typed request DTO,
2. calls the matching direct service method,
3. returns the `DiscordCommandResult`.

Rules:

- keep helpers small and deterministic
- one helper per command event family

## Step 3: Service implementation

Create or extend a service under `src/services/`.

Service requirements:

- validate permissions and prerequisites
- call repositories and APIs
- return `DiscordCommandResult`
- never send Discord messages directly
- when building user-facing text, pass view data into the Localizer and keep the final wording/layout in the lang files

## Step 4: Command and UI entry points

Add command registration in the matching module under:

- `src/entrypoints/discord/commands/`

If the flow is form-based, add or extend UI components under:

- `src/entrypoints/discord/ui/`

Rules:

- command layer performs transport-level checks and normalization
- service layer owns all business decisions
- UI components call through the same helper path as root commands

## Step 5: Wiring in bootstrap modules

Instantiate repositories, services, pipelines/orchestrators, and entrypoints in
the matching split bootstrap module:

- `src/bootstrap/core.py` for persistence, localization, and shared gateways
- `src/bootstrap/services.py` for application services and UI query bundles
- `src/bootstrap/runtime.py` for background workers and runtime entrypoints

If wiring is missing:

- commands register in Discord,
- the direct service call path is incomplete.

## Step 6: Testing

Minimum expected coverage:

1. service unit tests for action/permission/validation paths,
2. runtime behavior tests for downstream side effects,
3. UI flow guard tests for joined/permission preconditions.

Recommended commands:

```powershell
docker compose run --rm app pytest src/tests -q
docker compose run --rm app ruff check src
```

## Step 7: Documentation updates

Update only the canonical doc for each concern:

- command syntax and parameters -> `docs/commands_reference.md`
- runtime behavior and flow ownership -> `docs/architecture.md`
- data model -> `docs/database.md`
- test strategy and QA execution -> `docs/testing_playbook.md`

This keeps one authoritative source per topic and prevents duplicated guidance.

## Common failure points

- command registered but service not wired in the split bootstrap modules
- typed request added but dispatch helper not implemented
- service logic placed in adapter/UI instead of service layer
- schema changed without repository updates
- missing tests for denial and validation paths

## Rule of thumb

If code both parses Discord I/O and decides business outcomes, split it:

- adapter/UI handles interaction transport,
- service handles business logic,
- repository handles persistence.

