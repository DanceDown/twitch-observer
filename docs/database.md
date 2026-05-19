# Database

This document describes the persisted data model at a high level. For exact SQL,
see [src/database/schema.sql](../src/database/schema.sql).

## Current schema assumption

The project currently treats `schema.sql` as the canonical schema definition.
During the current test phase, incompatible local schema drift should be solved
by resetting local persisted database state instead of carrying forward runtime
schema evolution layers.

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
- `last_api_refresh_at`

This cache is warmed from IRC metadata when possible and refreshed from Helix
only when needed.

## Tracking scope

### `channel`

Stores tracked Twitch channels per Discord context.

Important fields:

- `thread_id`
- `twitch_channel_id`
- optional color override
- `is_live`
- `last_live_status_at`

One tracked channel means:

- the IRC adapter should read that chat when needed
- patterns may scope to that channel
- the live monitor should include it in batched `Get Streams` polling

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
- `notify`

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

## Relationship summary

- one `thread` has many tracked `channel`, `tracked_user`, `pattern`, `adapter_event`, and `user_permissions` rows
- one `pattern` may have many channel and user scope rows, and at most one `reply`
- one `adapter_event` may have multiple actions keyed by `action_type`
- one `thread` may optionally link one `twitch_account`
