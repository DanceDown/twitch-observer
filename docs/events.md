# Runtime DTOs

The runtime no longer uses an in-process event bus.

Instead, it uses typed DTOs at direct call boundaries:

- Discord request DTOs for command and UI-triggered service calls
- `TwitchChatMessageEvent` as the normalized Twitch IRC chat input object
- `TwitchChannelLiveStateChangedEvent` as the normalized live-state transition object

These types live in focused modules now, but they are plain data contracts, not
publish/subscribe bus messages.

Current module split:

- `src/events/commands.py`
- `src/events/discord_results.py`
- `src/events/pattern_scopes.py`
- `src/events/twitch_events.py`
- `src/events/ui_flow.py`

## `TwitchChatMessageEvent`

Produced by the Twitch IRC entrypoint and passed directly into
`ChatMessageProcessingService`.

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

## `TwitchChannelLiveStateChangedEvent`

Produced by `TwitchLiveMonitorService` when a tracked channel changes state and
passed directly into `LiveStateChangeOrchestrator`.

Important fields:

- `twitch_channel_id`
- `twitch_channel_login`
- `is_live`
- `changed_at`
