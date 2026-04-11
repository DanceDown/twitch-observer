# Events

This project uses an in-process event bus to decouple adapters from services.

## Goal

Adapters should only talk to external systems and normalize incoming data. They
should not contain business logic.

Services should react to normalized events and implement the actual rules.

## Current event flow

### Twitch message flow

1. A Twitch IRC line arrives in the anonymous IRC adapter.
2. The adapter parses the raw IRC message.
3. If the message is a chat message (`PRIVMSG`), the adapter converts it into a
   `TwitchChatMessageEvent`.
4. The adapter publishes the event to the event bus.
5. Every subscribed service receives the same normalized event.
6. Services decide what to do:
   persist it, evaluate patterns, send Discord notifications, trigger
   auto-replies later, and so on.

### Discord command flow

1. A slash command is invoked with a focused parameter set.
2. The Discord adapter normalizes the input values.
3. The Discord adapter publishes one internal command event.
4. A service handles the event and completes the attached result future.
5. The Discord adapter turns that result into a standardized embed response.

## Current event types

### `discord.channel.requested`

Represents the normalized `/channel` workflow from Discord.

Relevant fields:

- `discord_channel_id`: the Discord channel, thread, or DM where the command
  was invoked
- `requester_id`: the Discord user that invoked the command
- `action`: `add` or `remove`
- `twitch_channel_login`: the user-provided Twitch login
- `result_future`: future completed by the channel service with the command
  outcome

### `discord.pattern.requested`

Represents the normalized `/ping` or `/regex` workflow from Discord.

Relevant fields:

- `discord_channel_id`: the Discord channel, thread, or DM where the command
  was invoked
- `requester_id`: the Discord user that invoked the command
- `action`: `add` or `remove`
- `pattern_text`: the plain text ping or regex source
- `pattern_id`: optional stable ID used for quick removal
- `is_regex`: whether the pattern should be interpreted as regex
- `channel_scope_mode`: `all_tracked`, `only_selected`, or `all_except_selected`
- `twitch_channel_logins`: optional selected Twitch channel logins for that scope
- `user_scope_mode`: `all_users`, `only_selected`, or `all_except_selected`
- `twitch_user_logins`: optional selected Twitch user logins for that scope
- `sub_state`: `all`, `non_subs`, or `subs`
- `offline_state`: `both`, `offline`, or `online`
- `case_sensitive`: whether the match is case-sensitive
- `color`: optional embed color override
- `result_future`: future completed by the pattern service with the command
  outcome

### `discord.show.requested`

Represents the normalized `/show` workflow from Discord.

Relevant fields:

- `discord_channel_id`: the Discord channel, thread, or DM where the command
  was invoked
- `requester_id`: the Discord user that invoked the command
- `sections`: one or more requested overview sections
- `result_future`: future completed by the show service with the rendered
  result

### `discord.account.requested`

Represents the normalized `/account` workflow from Discord.

Relevant fields:

- `requester_id`: the Discord user that invoked the command
- `action`: `link`, `unlink`, or `show`
- `result_future`: future completed by the account service with the command
  outcome

### `discord.reply.requested`

Represents the normalized `/reply` workflow from Discord.

Relevant fields:

- `discord_channel_id`: the Discord channel, thread, or DM where the command
  was invoked
- `requester_id`: the Discord user that invoked the command
- `action`: `add` or `remove`
- `pattern_id`: stable pattern ID shown by `/show`
- `message`: optional reply text for `add`
- `reply_as_reply`: whether Twitch should reply directly to the matched message
- `result_future`: future completed by the reply service with the command
  outcome

### `twitch.chat.message`

Represents one normalized Twitch chat message.

Relevant fields:

- `channel_login`: lowercased Twitch channel login, for example `shroud`
- `author_login`: lowercased Twitch user login
- `author_display_name`: Twitch display name as shown in chat
- `content`: message text
- `message_id`: Twitch message identifier if available
- `broadcaster_id`: Twitch room / broadcaster id if available
- `author_id`: Twitch user id if available
- `reply_parent_message_id`: parent message id when the message is a reply
- `sent_at`: normalized UTC timestamp
- `raw_tags`: original Twitch IRC tags for debugging and future features

## Why this helps

- New adapters can publish the same event shape later, even if they do not use
  IRC.
- New services can subscribe without changing adapter code.
- The business logic stays modular and testable.
