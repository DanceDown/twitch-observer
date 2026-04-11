## Contents

This document explains the current architectural direction of the Twitch
Observer and how the major parts fit together.

## Internal Structure

### Adapters

Adapters are bindings to external systems. In the current implementation these
include:

- the Discord bot and slash commands
- the anonymous Twitch IRC connection used for read-only chat intake
- the Twitch Helix API used for validation, account linking, and auto-replies

### Database

The database layer opens the PostgreSQL connection and exposes repository-style
access to persisted data.

### Events

The central event bus lives here. Adapters publish normalized events, and
services subscribe to the events they care about.

### Services

Services implement business logic. They react to events, validate data, call
repositories, and optionally trigger secondary side effects.

### Tests

Unit tests focus on service behavior, event flows, and helper utilities.

### Utils

Shared helper functions that do not belong to one specific service.

### Main

`main.py` wires everything together:

- configuration
- database
- repositories
- event bus
- services
- Discord adapter
- Twitch adapters

## Current Data Flow

The application follows this flow:

1. an adapter receives external input
2. the adapter normalizes it into an internal event
3. the event bus dispatches the event
4. one or more services react
5. services read or write PostgreSQL data
6. services may emit a user-facing side effect, such as a Discord embed or a
   Twitch reply

## Current Concrete Flows

### Twitch message intake

1. `twitch_irc` receives a Twitch IRC `PRIVMSG`
2. it creates a `TwitchChatMessageEvent`
3. `MessageIngestService` stores the message
4. `PatternTrackingService` evaluates the message against active patterns
5. if a pattern matches, one Discord embed is sent
6. `AutoReplyService` evaluates the same message and may send one Twitch reply

### Discord configuration command

1. a Discord slash command is executed
2. the Discord adapter normalizes it into an event such as
   `DiscordPatternRequestedEvent`
3. the event bus dispatches the event
4. the corresponding service validates ownership and input
5. repositories persist the new state
6. the Discord adapter renders the returned `DiscordCommandResult` as an embed

## Important Architectural Choices

### Anonymous Twitch IRC for reading

The current read path uses anonymous Twitch IRC instead of EventSub.

Reason:

- the project explicitly prefers anonymous read access for public chat intake
- EventSub requires authenticated access for chat events
- anonymous IRC is therefore the better fit for this specific product goal

### Separate adapters, events, and services

Adapters should stay thin.

They should:

- talk to external systems
- normalize input
- publish events
- render returned results

They should not contain business rules.

Business rules belong in services.

### Shared match logic

Patterns are the single source of truth for deciding whether a Twitch message
matches.

That means:

- tracking notifications
- auto-replies
- future convenience commands

all build on the same underlying pattern semantics.

### Explicit Discord context lifecycle

A Discord channel or thread is not created implicitly anymore.

It must be explicitly joined through `/join` and can be fully removed through
`/leave`.

That keeps configuration predictable and avoids hidden database side effects.
