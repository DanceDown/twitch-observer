# Twitch User Caching and Live-State Flow

This document explains the current runtime flow for:

- incoming Twitch chat messages
- pattern matching
- author and channel profile resolution
- Twitch API usage
- persistent and in-memory caching
- persisted live/offline channel state
- pattern-bound and channel-event auto-replies

It is the detailed companion to [docs/architecture.md](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\docs\architecture.md:1>) and focuses on the hot path and its performance tradeoffs.

## Goals

The current implementation is built around four rules:

- keep the message hot path cheap
- persist useful Twitch identity data in PostgreSQL
- use Helix only when cache quality is insufficient
- keep live/offline matching independent from per-message live API checks

The important consequence is that incoming chat events are allowed to update the cache, but they should not trigger avoidable external API calls.

## Main Components

### Twitch IRC adapter

File:

- [src/adapters/twitch_irc/__init__.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\adapters\twitch_irc\__init__.py:64>)

This adapter parses `PRIVMSG` lines and publishes `TwitchChatMessageEvent`.

Useful IRC fields for caching:

- `author_id`
- `author_login`
- `author_display_name`
- `broadcaster_id`
- `channel_login`
- `color`
- `message_id`

Important limitation:

- IRC does not provide a profile image URL

### Twitch user directory

File:

- [src/services/twitch_user_directory_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\twitch_user_directory_service.py:23>)

This is the central user-resolution layer. It combines:

- an in-memory LRU
- the persistent `twitch_user_cache` table
- Helix fallback when cache data is missing or considered too old

### Twitch user ingest service

File:

- [src/services/twitch_user_directory_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\twitch_user_directory_service.py:228>)

This service listens to every `TwitchChatMessageEvent` and updates cached Twitch identity data directly from IRC metadata without using Helix.

### Pattern tracking

File:

- [src/services/pattern_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\pattern_service.py:1029>)

This service evaluates incoming messages against stored patterns and sends Discord tracking embeds.

### Auto-replies

File:

- [src/services/reply_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\reply_service.py:255>)

This service evaluates incoming messages against reply-enabled patterns and sends Twitch chat messages when they match.

### Channel live-state services

File:

- [src/services/channel_live_state_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\channel_live_state_service.py:1>)

These services move live/offline state into its own domain flow:

- Discord commands publish manual live-state changes
- the event bus broadcasts them as domain events
- a persistence service writes the state into tracked channel rows
- channel-event auto-replies consume the same domain event

## Storage Layers

### Persistent Twitch user cache

Schema:

- [src/database/schema.sql](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\database\schema.sql:35>)

Table:

- `twitch_user_cache`

Stored fields:

- `twitch_user_id`
- `twitch_login`
- `display_name`
- `profile_image_url`
- `updated_at`
- `last_api_refresh_at`

Meaning:

- `updated_at` tracks when the visible cached identity changed
- `last_api_refresh_at` tracks when Helix last refreshed that user

### In-memory Twitch user LRU

Code:

- [src/services/twitch_user_directory_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\twitch_user_directory_service.py:25>)

This cache sits in front of PostgreSQL and stores the most recently used Twitch user records.

Its size is configured through:

- `TWITCH_USER_CACHE_MEMORY_SIZE`

### Persisted tracked channel state

Schema:

- [src/database/schema.sql](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\database\schema.sql:72>)

Tracked channel rows now store:

- `is_live`
- `last_live_status_at`

That means pattern evaluation no longer needs to ask Twitch whether a broadcaster is currently live for every matching message.

### Channel event auto-replies

Schema:

- [src/database/schema.sql](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\database\schema.sql:194>)

Table:

- `channel_event_reply`

Stored fields:

- `thread_id`
- `twitch_channel_id`
- `event_state`
- `reply_message`
- `disabled`

This table stores replies triggered by a tracked channel becoming `online` or `offline`.

## Flow: Incoming Message

### 1. IRC message arrives

The Twitch IRC adapter parses the message and publishes a `TwitchChatMessageEvent`.

### 2. The event bus fans the message out

The same message is dispatched to multiple services:

- message persistence
- Twitch user cache ingest
- pattern tracking
- pattern-based auto-replies

### 3. The persistent user cache is updated from IRC metadata

`TwitchUserDirectoryIngestService` calls `observe_chat_message(...)`.

What is written immediately:

- author ID
- author login
- author display name
- broadcaster ID
- channel login

What is not available from IRC:

- `profile_image_url`

This means every seen chatter becomes known to the application immediately, even if that user was never manually added through `/user`.

### 4. Pattern matching runs

`PatternTrackingService` loads:

- all interested threads for the broadcaster
- all active patterns for each thread
- the tracked channel row for that broadcaster inside the thread

Then it evaluates:

- text match semantics
- scope filters
- subscriber filters
- persisted channel live/offline state

### 5. Pattern-based auto-replies run

`AutoReplyService` follows the same broad lookup path, but sends Twitch chat messages instead of Discord embeds.

## Flow: User Profile Resolution

### Cache-first lookup behavior

All user resolution goes through `TwitchUserDirectoryService`.

The lookup order is:

1. in-memory LRU
2. PostgreSQL `twitch_user_cache`
3. Helix fallback only if necessary

### What counts as “necessary”

Helix fallback is allowed when:

- no cached user exists at all
- the cached user has no `profile_image_url`
- the last API refresh is older than the configured refresh interval

That refresh interval is controlled by:

- `TWITCH_USER_CACHE_API_REFRESH_SECONDS`

### Why the hot path is now allowed to call Helix again

There is one intentional exception to the “avoid Helix in the hot path” rule:

- if an embed wants a profile image
- and the cache entry exists but has no profile image yet

then the hot path may do a one-time Helix refresh for that user and store the result back into the cache.

This is considered acceptable because:

- it happens only once per uncached or incomplete user
- the result is persisted
- later messages become cheap again

### What happens on refresh failure

If cached data exists but a refresh fails:

- the cached user is still returned
- the message flow continues
- the app avoids breaking tracking or auto-replies just because a refresh failed

## Flow: Live/Offline State

### Manual Discord commands

Files:

- [src/adapters/discord/commands/live_state_commands.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\adapters\discord\commands\live_state_commands.py:1>)
- [src/adapters/discord/ui/live_state_ui.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\adapters\discord\ui\live_state_ui.py:1>)

The `/live` and `/offline` commands:

- open a modal
- let the user select one already tracked channel
- publish a normalized Discord request event

### Domain event emission

`ChannelLiveStateCommandService` validates the request and publishes:

- `TwitchChannelLiveStateChangedEvent`

File:

- [src/services/channel_live_state_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\channel_live_state_service.py:24>)

### Persistence

`ChannelLiveStatePersistenceService` listens to that domain event and updates all matching tracked channel rows in the database.

That means:

- all threads tracking the same broadcaster receive the same stored live state
- no per-message Twitch live-status API call is needed for matching

### Pattern matching against live state

`offline_state` filters now use the persisted `channel.is_live` value.

So:

- `online` means the stored channel row says the broadcaster is live
- `offline` means the stored channel row says the broadcaster is offline
- unknown state means matching does not force either side

The important performance effect is:

- no `is_user_live(...)` request in the per-message pattern path

## Flow: Channel Event Auto-Replies

### Configuration

The `/reply` UI can now attach replies to:

- normal ping or regex patterns
- tracked channel `online` events
- tracked channel `offline` events

Files:

- [src/adapters/discord/ui/reply_ui.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\adapters\discord\ui\reply_ui.py:1>)
- [src/services/reply_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\reply_service.py:33>)

### Execution

`ChannelEventAutoReplyService` listens to `TwitchChannelLiveStateChangedEvent`.

File:

- [src/services/reply_service.py](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\src\services\reply_service.py:571>)

When a live-state change happens, it:

- loads event replies for that broadcaster and state
- checks whether each thread is still enabled
- checks whether a linked Twitch account is available
- sends the configured Twitch chat message

Supported placeholders for channel-event replies:

- `{CHANNEL}`
- `{STATE}`

## When Twitch API Calls Happen

### Helix `Get Users` is used for

- explicit validation-heavy commands such as `/channel`, `/user`, and `/write`
- cache misses in the user directory
- cached users missing `profile_image_url`
- cached users whose last API refresh is older than `TWITCH_USER_CACHE_API_REFRESH_SECONDS`

### Helix `Get Users` is not used for

- ingesting every incoming chat message
- storing author login and display name from IRC
- offline-state checks during normal pattern matching
- offline-state checks during pattern-based auto-reply matching

### Other Twitch API calls still exist

Independent from user caching, the app still uses Twitch APIs for:

- account linking and token validation
- token refresh
- sending Twitch chat messages

## When Cached Data Is Updated

### Login and display name

Updated from IRC:

- on every incoming message

Reason:

- the data is already present
- no external request is needed

### Profile image URL

Updated from Helix:

- on cache miss
- on incomplete profile data
- on configured staleness

Reason:

- IRC does not expose profile images

### Live/offline channel state

Updated from domain events:

- currently through `/live` and `/offline`
- later also suitable for any future automated live-state adapter

Reason:

- it keeps live/offline semantics explicit and decoupled from message volume

## Performance Hotspots

### 1. External Twitch API calls

This is still the clearest expensive resource because it adds:

- network latency
- rate-limit pressure
- failure modes outside the process

That is why cached IRC identity data is preferred wherever possible.

### 2. Pattern evaluation volume

Per-message work still grows with:

- number of tracked threads for a broadcaster
- number of active patterns per thread
- regex complexity
- scope expansion for tracked-user filters

### 3. Database reads

PostgreSQL is much cheaper than Helix, but repeated reads still cost more than in-memory hits.

That is why the directory service uses:

- PostgreSQL for persistence
- an in-memory LRU for repetition-heavy lookups

### 4. Discord and Twitch outbound sends

If many messages match or many live-state event replies fire, outbound network operations can become the next bottleneck after pattern evaluation.

## Configuration

The most relevant tuning values are intentionally centralized in environment variables instead of being spread as fixed strategy numbers through the codebase.

Relevant cache and runtime knobs include:

- `TWITCH_USER_CACHE_MEMORY_SIZE`
- `TWITCH_USER_CACHE_API_REFRESH_SECONDS`
- `TWITCH_ACCOUNT_TOKEN_REFRESH_SKEW_SECONDS`
- `TWITCH_APP_ACCESS_TOKEN_REFRESH_SKEW_SECONDS`
- `TWITCH_DEVICE_FLOW_POLL_INTERVAL_SECONDS`
- `TWITCH_DEVICE_FLOW_SLOWDOWN_STEP_SECONDS`
- `DISCORD_PRESENCE_POLL_INTERVAL_SECONDS`
- `DISCORD_PRESENCE_LOOKBACK_MINUTES`
- `DISCORD_PRESENCE_MESSAGE_LIMIT`
- `DISCORD_PRESENCE_MAX_STATUS_LENGTH`
- `IRC_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS`

See:

- [.env.example](<C:\Users\Dance\Desktop\Twitch Bot\Twitch_Bot\.env.example:1>)

## Why This Strategy Was Chosen

The current design deliberately uses a hybrid model:

- IRC is the cheapest source for login and display-name freshness
- PostgreSQL keeps user identity data across restarts
- the in-memory LRU keeps frequent lookups cheap
- Helix fills in the gaps that IRC cannot provide, especially profile images
- live/offline state is persisted once and reused many times

The main tradeoff is intentional:

- a brand-new or stale profile lookup may make one message slower

That cost is accepted because the result is cached and later messages become cheap again.
