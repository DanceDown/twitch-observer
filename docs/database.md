# Database Concept

This document describes the current persisted domain model of the Twitch
Observer.

## Core idea

The model centers around five main concepts:

1. `thread`
   - one Discord channel, thread, or DM configuration root
2. `channel`
   - one tracked Twitch channel inside that Discord context
3. `pattern`
   - one match rule for tracking and reply logic
4. `reply`
   - one optional auto-reply attached to one pattern
5. `message`
   - one observed Twitch message

Additionally, Twitch login state is stored in:

- `twitch_account`
- `twitch_device_flow`

## Important modeling decisions

### No separate stalk or block tables

There are intentionally no dedicated `stalked_user`, `blocked_user`,
`blocked_ping`, or `blocked_regex` tables.

Those cases are represented through the scope system of `pattern`:

- channel scope
- user scope
- sub-state
- offline-state
- regex or ping mode

This keeps the model smaller and avoids historical workaround tables.

### Replies are separate from patterns

A reply is attached to one pattern, but it lives in its own table.

That allows:

- keeping replies even if a linked account temporarily expires
- disabling replies without deleting them
- evolving reply-specific features without bloating `pattern`

### Pattern priority decides match order

Patterns are evaluated in descending priority order.

Once one pattern matches, later patterns are not considered for that message in
the tracking flow. Auto-replies follow the same priority order.

## Entities

## `twitch_account`

Stores one linked Twitch account record that may be attached to exactly one
Discord context through `thread.account_id`.

That means the same Discord user may have multiple stored Twitch account links
across different Discord contexts.

Key fields:

- `discord_user_id`
- `twitch_user_id`
- `twitch_login`
- `client_id`
- `access_token`
- `refresh_token`
- `expires_at`
- `scope`
- `token_type`

## `twitch_device_flow`

Stores one pending or failed Twitch Device Code Flow per Discord context.

Key fields:

- `discord_user_id`
- `discord_channel_id`
- `device_code`
- `user_code`
- `verification_uri`
- `interval_seconds`
- `expires_at`
- `scope`
- `status`
- `last_error`

## `thread`

Represents one Discord-side configuration root.

Key fields:

- `thread_id`
- `owner_id`
- `discord_channel_id`
- `account_id`
- `enabled`
- `color`

Notes:

- one Discord channel ID maps to exactly one configuration root
- `account_id` links the context to the exact Twitch account used for
  auto-replies and manual Twitch writes
- `enabled = false` pauses tracking and auto-replies without deleting config

## `channel`

Stores which Twitch channels are tracked in one Discord context.

Key fields:

- `thread_id`
- `twitch_channel_id`
- `color`

Notes:

- `color` is a channel-level embed override
- removing a channel is restricted if a pattern scope still references it

## `pattern`

Stores one match rule.

Key fields:

- `thread_id`
- `p_index`
- `regex`
- `channel_scope_mode`
- `user_scope_mode`
- `sub_state`
- `offline_state`
- `is_regex`
- `case_sensitive`
- `color`
- `disabled`
- `notify`
- `priority`

Notes:

- pings are stored in the same table as regexes
- a ping is matched as a whole-word search
- `case_sensitive` applies to both ping and regex matching
- `priority` is user-adjustable

## `pattern_channel_scope`

Stores explicit Twitch channel selections or exclusions for a pattern.

Used when `channel_scope_mode` is:

- `only_selected`
- `all_except_selected`

If the mode is `all_tracked`, no rows are required.

## `pattern_user_scope`

Stores explicit Twitch user selections or exclusions for a pattern.

Used when `user_scope_mode` is:

- `only_selected`
- `all_except_selected`

If the mode is `all_users`, no rows are required.

## `reply`

Stores one optional auto-reply attached to one pattern.

Key fields:

- `thread_id`
- `p_index`
- `reply_message`
- `reply_as_reply`
- `disabled`

Notes:

- one pattern can have at most one reply
- a reply is preserved even if the linked Twitch account expires
- a disabled reply stays stored and can later be enabled again

## `user_permissions`

Stores explicitly granted extra permissions for non-owner Discord users inside
one thread.

Key fields:

- `discord_user_id`
- `thread_id`
- `permissions`

Notes:

- the owner is not stored here because the owner always has full access
- permissions are stored as a bitmask
- implication rules such as `manage_patterns -> toggle_patterns` are handled in
  application code

## `message`

Stores observed Twitch chat messages.

Key fields:

- `message_id`
- `twitch_channel_id`
- `timestamp`
- `twitch_user_id`
- `username`
- `content`
- `is_reply_to`
- `is_bot`

Current status:

- messages are persisted
- higher-level history features are not implemented yet

## Color inheritance

Discord embed color resolution currently follows this priority:

1. `pattern.color`
2. `channel.color`
3. `thread.color`
4. Twitch author color from IRC tags
5. gray fallback

This is a presentation rule only.
