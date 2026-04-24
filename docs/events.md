# Events

This project uses an in-process event bus so adapters stay thin and services own
the actual rules.

## Main event families

### Discord command requests

The Discord adapter normalizes slash commands into typed internal events such
as:

- `discord.thread.requested`
- `discord.channel.requested`
- `discord.channel_event.requested`
- `discord.pattern.requested`
- `discord.pattern.edit.requested`
- `discord.reply.requested`
- `discord.account.requested`
- `discord.write.requested`
- `discord.permission.requested`
- `discord.show.requested`

Each command event carries:

- the Discord context
- the requester
- normalized command parameters
- a `result_future` completed by the handling service

### Twitch chat input

`twitch.chat.message` is emitted by the anonymous IRC adapter for each incoming
`PRIVMSG`.

Important fields:

- `channel_login`
- `author_login`
- `author_display_name`
- `content`
- `message_id`
- `broadcaster_id`
- `author_id`
- `reply_parent_message_id`
- `sent_at`

This is the hot-path event that drives message persistence, user-cache warming,
pattern matching, Discord notifications, and pattern-bound auto-replies.

### Tracked-channel lifecycle

`twitch.tracked_channels.changed` is emitted whenever tracked channels are added
or removed. It allows background infrastructure such as the live monitor to
refresh without coupling it to command handlers.

### Channel live-state transitions

`twitch.channel_live_state.changed` is emitted when the app-token live monitor
observes an actual state change for a tracked channel.

Important fields:

- `twitch_channel_id`
- `twitch_channel_login`
- `is_live`
- `changed_at`

This event fans out to:

- `ChannelLiveStatePersistenceService`
- `ChannelEventNotificationService`
- `ChannelEventAutoReplyService`

## Why this helps

- adapters only translate I/O into domain events
- services stay testable and reusable
- new sources can publish existing event shapes without rewriting business logic
