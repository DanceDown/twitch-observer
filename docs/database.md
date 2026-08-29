# Database

This document describes the persisted data model at a high level. For exact SQL,
see [src/database/schema.sql](../src/database/schema.sql).

## Current schema assumption

`schema.sql` defines the latest fresh-install schema.

At application startup, the app applies ordered SQL migrations from
`src/database/migrations/` and records them in `schema_migrations`.

This means:

- a brand-new database gets the newest shape from `schema.sql`
- an existing database is upgraded in place on restart
- each migration file should stay idempotent when possible

## Design goals

- keep Discord-context configuration isolated per channel, thread, or DM
- persist enough runtime state to avoid expensive Twitch API calls
- separate message-driven rules from source-driven event actions

## Core ownership model

### `thread`

`thread` is the configuration root for one Discord context.

It stores:

- `discord_channel_id`
- `owner_id`
- optional linked Twitch `account_id`
- enabled flag
- default embed color

Most other tables hang off `thread_id`.

## Twitch identity and auth

### `twitch_account`

Stores linked Twitch accounts used for writing to Twitch.

Important fields:

- `discord_user_id`
- `twitch_user_id`
- `twitch_login`
- access and refresh tokens
- token expiry and scopes

This table is not used for background live monitoring.

### `twitch_device_flow`

Stores pending Twitch Device Code Flow sessions while a Discord user is linking
an account.

### `twitch_user_cache`

Persistent cache of Twitch user metadata.

Important fields:

- `twitch_user_id`
- `twitch_login`
- `display_name`
- `profile_image_url`

This cache is warmed from IRC metadata when possible and refreshed from Helix
only when needed.

The background refresh worker also revalidates the full persistent cache in
batches on one shared interval. `updated_at` tracks when stored metadata last
changed; the schema no longer stores a separate "last refresh" timestamp.

## Tracking scope

### `channel`

Stores tracked Twitch channels per Discord context.

Important fields:

- `thread_id`
- `twitch_channel_id`
- optional color override

One tracked channel means:

- the IRC adapter should read that chat when needed
- patterns may scope to that channel
- the live monitor should include it in batched `Get Streams` polling

This table is the per-thread subscription/config layer. It does not own the
global live/offline state anymore. Runtime channel discovery for IRC and the
live monitor is based on this table, not on `tracked_channel_state`, so a
missing state row cannot hide a tracked channel.

### `tracked_channel_state`

Stores the app-owned global live-state snapshot per tracked broadcaster.

Important fields:

- `twitch_channel_id`
- `is_live`
- `last_live_status_at`

This table is the single persisted source of truth for live/offline state.
Thread-scoped channel reads join this state back in as needed.

Migrations backfill missing state rows from `channel`. Repository writes also
create the state row on demand for a tracked channel.

### `tracked_user`

Stores Twitch users that may be referenced by pattern user scopes.

## Message-driven behavior

### `pattern`

Stores the matching rules for Twitch chat messages.

Important modeling detail:

- `pattern_id` is the stable internal pattern identifier used by repositories,
  replies, and Discord interactions
- user-facing pattern numbers are rendered densely per thread at presentation
  time and are not persisted

Important fields:

- `regex`
- `is_regex`
- `case_sensitive`
- `channel_scope_mode`
- `user_scope_mode`
- `sub_state`
- `offline_state`
- `priority`
- `disabled`

### `pattern_channel_scope`

Selected channel scope rows for patterns that do not apply to all tracked
channels.

### `pattern_user_scope`

Selected user scope rows for patterns that do not apply to all users or all
tracked users.

### `reply`

Stores the optional Twitch auto-reply attached to one pattern.

Important fields:

- `reply_message`
- `reply_as_reply`
- `disabled`

There is at most one pattern reply per pattern.

## Source-driven event behavior

### `adapter_event`

Stores a configured external trigger inside one Discord context.

Use:

- Twitch channel `stream.online`
- Twitch channel `stream.offline`

The shape is intentionally generic:

- `adapter_key`
- `subject_type`
- `subject_id`
- `event_key`
- `disabled`

### `adapter_event_action`

Stores follow-up actions for one configured `adapter_event`.

Action types:

- Discord notification
- Twitch send-message auto-reply

This is the source-driven counterpart to `reply`.

## Permissions and message history

### `user_permissions`

Stores explicit per-user permission overrides inside one Discord context.

### `message`

Stores observed Twitch chat messages.

Important fields:

- `message_id`
- `twitch_channel_id`
- `timestamp`
- `twitch_user_id`
- `username`
- `content`
- `is_reply_to`
- `is_bot`

This supports Discord notifications, replies, presence summaries, and future
inspection/debug flows.

`thread_message_match` links matched messages back to threads. It is indexed by
`message_id` for reply lookup and cleanup paths.

## Relationship summary

- one `thread` has many tracked `channel`, `tracked_user`, `pattern`, `adapter_event`, and `user_permissions` rows
- one `pattern` may have many channel and user scope rows, and at most one `reply`
- one `adapter_event` may have multiple actions keyed by `action_type`
- one `thread` may optionally link one `twitch_account`
