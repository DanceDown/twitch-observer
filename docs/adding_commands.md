# Adding Commands

This guide explains how to add a Discord feature as one vertical slice across
adapter, events, services, persistence, and tests.

## Scope

This document covers implementation workflow.  
Command behavior details belong in [commands_reference.md](commands_reference.md).

## Architecture boundaries

- `src/adapters/discord/commands/*`
  - command registration and interaction entry points
- `src/adapters/discord/ui/*`
  - modals, menus, and component-driven forms
- `src/adapters/discord/dispatch.py`
  - typed event dispatch helpers
- `src/events/event_types.py`
  - event names and payload dataclasses
- `src/services/*`
  - business logic and orchestration
- `src/database/*`
  - schema, repository contracts, and implementations
- `src/main.py`
  - dependency wiring

## Implementation workflow

1. Define domain behavior and data ownership.
2. Add or extend persisted schema when needed.
3. Add/extend record and repository contracts.
4. Add typed event payload and event name.
5. Add a dispatch helper.
6. Implement service logic and subscribe in `__post_init__`.
7. Add command registration and UI interaction entry points.
8. Wire service/repository in `src/main.py`.
9. Add tests for service behavior and affected flows.
10. Update docs for command surface and operational behavior.

## Step 1: Event contract

Add an `EventType` member in `src/events/event_types.py`, then add a dedicated
event payload dataclass containing:

- context identity (`discord_channel_id`, `requester_id`)
- normalized command data
- `result_future`

Rules:

- payload fields must be normalized and explicit
- avoid passing raw Discord objects into services

## Step 2: Dispatch helper

Add a helper in `src/adapters/discord/dispatch.py` that:

1. creates a future,
2. publishes the typed event,
3. awaits and returns the `DiscordCommandResult`.

Rules:

- keep helpers small and deterministic
- one helper per command event family

## Step 3: Service implementation

Create or extend a service under `src/services/`.

Service requirements:

- subscribe in `__post_init__`
- validate permissions and prerequisites
- call repositories and APIs
- return `DiscordCommandResult`
- never send Discord messages directly

## Step 4: Command and UI entry points

Add command registration in the matching module under:

- `src/adapters/discord/commands/`

If the flow is form-based, add or extend UI components under:

- `src/adapters/discord/ui/`

Rules:

- command layer performs transport-level checks and normalization
- service layer owns all business decisions
- UI components dispatch through the same helper path as slash commands

## Step 5: Wiring in `src/main.py`

Instantiate repositories and services in `src/main.py`.

If wiring is missing:

- commands register in Discord,
- events are published,
- no service handles the request.

## Step 6: Testing

Minimum expected coverage:

1. service unit tests for action/permission/validation paths,
2. runtime behavior tests for downstream side effects,
3. UI flow guard tests for joined/permission preconditions.

Recommended commands:

```powershell
docker compose run --rm app pytest src/tests -q
docker compose run --rm app python -m ruff check src
```

## Step 7: Documentation updates

Update only the canonical doc for each concern:

- command syntax and parameters -> `docs/commands_reference.md`
- runtime behavior and flow ownership -> `docs/architecture.md`
- data model -> `docs/database.md`
- test strategy and QA execution -> `docs/testing_playbook.md`

This keeps one authoritative source per topic and prevents duplicated guidance.

## Common failure points

- command registered but service not wired in `main.py`
- event type added but dispatch helper not implemented
- service logic placed in adapter/UI instead of service layer
- schema changed without repository updates
- missing tests for denial and validation paths

## Rule of thumb

If code both parses Discord I/O and decides business outcomes, split it:

- adapter/UI handles interaction transport,
- service handles business logic,
- repository handles persistence.
