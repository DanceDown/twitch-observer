# Command Reference

This is the authoritative command reference for the current Discord bot
surface.

All commands are slash commands.

All successful responses are embeds in the current Discord context.

Validation, permission, and lookup errors are normally ephemeral embeds.

## General Rules

### Joined context required

Most configuration commands require that the current Discord channel, thread, or
DM was explicitly joined first:

```text
/join
```

Without that, the bot returns `Not Joined`.

### Stable IDs

Patterns and replies use stable IDs that are shown by:

```text
/show section:pings
/show section:auto_replies
```

These IDs are then used for edit, enable, disable, and remove actions.

### Ping versus regex

There is only one rule command now:

```text
/ping ...
```

Whether a rule is treated as a normal ping or as a regex is controlled by the
`is_regex` parameter.

- `is_regex:false`
  - word-based ping matching
  - internally behaves like a whole-word search
- `is_regex:true`
  - Python regex matching

`case_sensitive` applies to both modes.

## Lifecycle Commands

### `/join`

Purpose:

- connect the current Discord context to the observer

Syntax:

```text
/join
```

Behavior:

- creates the configuration root for the current Discord channel, thread, or DM
- makes later `/channel`, `/ping`, `/reply`, `/permission`, and `/show`
  commands possible

### `/leave`

Purpose:

- disconnect the current Discord context from the observer
- delete all saved configuration that belongs to that context

Syntax:

```text
/leave
```

Behavior:

- opens a confirmation modal
- the user must explicitly confirm before deletion happens
- removes patterns, replies, channels, permissions, messages, and the Discord
  context itself

### `/on`

Purpose:

- temporarily enable tracking and auto-replies in the current Discord context

Syntax:

```text
/on
```

Behavior:

- preserves all saved configuration
- only re-enables processing

### `/off`

Purpose:

- temporarily disable tracking and auto-replies in the current Discord context

Syntax:

```text
/off
```

Behavior:

- preserves all saved configuration
- useful when the Discord channel should not be spammed for a while

### `/color`

Purpose:

- set or clear the default embed color for the current Discord context

Syntax:

```text
/color color:#7788ff
/color clear:true
```

Parameters:

- `color`
  - optional color in `#RRGGBB`
- `clear`
  - set to `true` to remove the stored context color

## Channel Commands

### `/channel add`

Purpose:

- add one tracked Twitch channel to the current Discord context

Syntax:

```text
/channel add channel_name:dancedown
```

Parameters:

- `channel_name`
  - Twitch login of the channel to track

Behavior:

- validates that the Twitch channel exists
- joins that Twitch channel on the IRC side if needed
- stores the channel in the current Discord context

### `/channel remove`

Purpose:

- remove one tracked Twitch channel from the current Discord context

Syntax:

```text
/channel remove channel_name:dancedown
```

Parameters:

- `channel_name`
  - Twitch login of the tracked channel to remove

Behavior:

- only works if no pattern still references that channel scope
- parts the Twitch IRC channel when no remaining Discord context needs it

### `/channel color`

Purpose:

- set or clear the embed color for one tracked Twitch channel

Syntax:

```text
/channel color channel_name:dancedown color:#55ccaa
/channel color channel_name:dancedown clear:true
```

Parameters:

- `channel_name`
  - tracked Twitch channel login
- `color`
  - optional color in `#RRGGBB`
- `clear`
  - set to `true` to remove the stored channel color

### `/live`

Purpose:

- manually mark one tracked Twitch channel as live

Behavior:

- opens a modal
- lets you choose one tracked channel from the current Discord context
- persists the live state through the event bus and the channel-state service
- may trigger configured channel-event auto-replies

### `/offline`

Purpose:

- manually mark one tracked Twitch channel as offline

Behavior:

- opens a modal
- lets you choose one tracked channel from the current Discord context
- persists the offline state through the event bus and the channel-state service
- may trigger configured channel-event auto-replies

## Pattern Commands

### `/ping add`

Purpose:

- create a new tracking rule

Syntax:

```text
/ping add text:hallo
/ping add text:^h[a4]llo$ is_regex:true
/ping add text:hallo channel_scope:only_selected channels:dancedown,other
/ping add text:hallo user_scope:only_selected users:alice,bob
```

Parameters:

- `text`
  - the ping text or regex source
- `is_regex`
  - `true` means regex mode
  - `false` means normal ping mode
  - default: `false`
- `channel_scope`
  - `all_tracked`
  - `only_selected`
  - `all_except_selected`
  - default: `all_tracked`
- `channels`
  - comma-separated tracked Twitch channel logins
  - only valid for `only_selected` or `all_except_selected`
- `user_scope`
  - `all_users`
  - `only_selected`
  - `all_except_selected`
  - default: `all_users`
- `users`
  - comma-separated Twitch user logins
  - only valid for `only_selected` or `all_except_selected`
- `sub_state`
  - `all`
  - `subs`
  - `non_subs`
  - default: `all`
- `offline_state`
  - `both`
  - `online`
  - `offline`
  - default: `both`
- `case_sensitive`
  - whether casing matters
  - default: `false`
- `color`
  - optional embed color in `#RRGGBB`

Behavior:

- validates regex syntax when `is_regex:true`
- validates selected channels against the already tracked channels of this
  Discord context
- validates selected users through Twitch
- computes a default priority from specificity unless you later override it

### `/ping remove`

Purpose:

- remove one existing rule by ID

Syntax:

```text
/ping remove id:3
```

Parameters:

- `id`
  - stable rule ID from `/show section:pings`

Behavior:

- works for both ping-mode and regex-mode rules

### `/ping disable`

Purpose:

- disable one existing rule without deleting it

Syntax:

```text
/ping disable id:3
```

Parameters:

- `id`
  - stable rule ID from `/show section:pings`

Behavior:

- the rule stays in the database
- no longer matches until re-enabled

### `/ping enable`

Purpose:

- re-enable one previously disabled rule

Syntax:

```text
/ping enable id:3
```

Parameters:

- `id`
  - stable rule ID from `/show section:pings`

### `/ping edit`

Purpose:

- change an existing rule in place

Syntax:

```text
/ping edit id:3 text:^hello$ is_regex:true
/ping edit id:3 priority:9
/ping edit id:3 channel_scope:only_selected channels:dancedown,other
/ping edit id:3 user_scope:all_except_selected users:alice
/ping edit id:3 color:#ff77aa
/ping edit id:3 clear_color:true
```

Parameters:

- `id`
  - stable rule ID from `/show`
- `text`
  - optional new ping text or regex source
- `is_regex`
  - optional switch between normal ping mode and regex mode
- `channel_scope`
  - optional new channel scope
- `channels`
  - optional comma-separated tracked Twitch channel logins
- `user_scope`
  - optional new user scope
- `users`
  - optional comma-separated Twitch user logins
- `sub_state`
  - optional new subscriber filter
- `offline_state`
  - optional new live/offline filter
- `case_sensitive`
  - optional new casing behavior
- `color`
  - optional new custom embed color
- `clear_color`
  - set to `true` to remove a previously stored custom color
- `priority`
  - optional manual priority from `0` to `9`

Behavior:

- only the provided fields change
- omitted fields keep their current values
- this is now also the place to change priority

## Reply Commands

### `/reply`

Purpose:

- manage auto-replies through one interactive form

Behavior:

- opens a form with `Add`, `Remove`, `Disable`, and `Enable`
- `Add` lets you attach a reply to:
  - one existing ping or regex rule
  - one tracked channel becoming `online`
  - one tracked channel becoming `offline`
- pattern-based replies may either send a normal Twitch message or reply directly to the matched Twitch chat message
- channel-event replies always send a normal Twitch message
- one pattern can have at most one attached pattern reply
- one tracked channel can have at most one configured reply per live-state event

Pattern placeholders:

- `{NAME}`
  - matched message author display name or login
- `{CHANNEL}`
  - Twitch channel login of the matched message
- `{MESSAGE}`
  - original matched message text

Channel-event placeholders:

- `{CHANNEL}`
  - tracked channel display name used for the event
- `{STATE}`
  - either `online` or `offline`

## Account Commands

### `/account link`

Purpose:

- start Twitch Device Code Flow for the current Discord context

Syntax:

```text
/account link
```

Behavior:

- creates a Twitch device-flow login session
- shows the activation URL and code
- the user confirms on Twitch
- the bot stores the linked Twitch account on the current Discord channel/thread afterwards
- only the thread owner may change which Twitch account is linked here

### `/account unlink`

Purpose:

- remove the Twitch account linked to the current Discord context

Syntax:

```text
/account unlink
```

Behavior:

- removes the Twitch account linked to the current Discord channel/thread
- only the thread owner may change which Twitch account is linked here

### `/account show`

Purpose:

- show the Twitch account link status for the current Discord context

Syntax:

```text
/account show
```

## Manual Twitch Write Command

### `/write`

Purpose:

- manually send one Twitch message
- optionally send it as a reply to a specific Twitch message

Syntax:

```text
/write channel_name:dancedown message:Hallo zusammen
/write channel_name:dancedown message:Stimme dir zu reply_to_message_id:abc123
```

Parameters:

- `channel_name`
  - tracked Twitch channel login that should receive the message
- `message`
  - Twitch chat text to send
- `reply_to_message_id`
  - optional Twitch message ID to reply to

Behavior:

- uses the Twitch account linked to the current Discord channel/thread
- requires the `send_twitch_messages` permission for non-owners
- only works for tracked Twitch channels in the current Discord context

## Permission Commands

### `/permission grant`

Purpose:

- grant one explicit permission to another Discord user in this context

Syntax:

```text
/permission grant user:@Example permission:manage_patterns
```

Parameters:

- `user`
  - Discord user to grant access to
- `permission`
  - one of:
    - `view`
    - `manage_channels`
    - `toggle_patterns`
    - `manage_patterns`
    - `toggle_replies`
    - `manage_replies`
    - `send_twitch_messages`
    - `control_observer`
    - `leave_context`
    - `manage_permissions`
    - `admin`

### `/permission revoke`

Purpose:

- revoke one explicit permission from another Discord user

Syntax:

```text
/permission revoke user:@Example permission:view
```

### `/permission clear`

Purpose:

- remove all explicitly granted permissions from one Discord user

Syntax:

```text
/permission clear user:@Example
```

Behavior:

- the owner always keeps full access
- explicit permissions are stored as a bitmask
- some permissions imply smaller ones internally

## Show Command

### `/show`

Purpose:

- inspect one saved configuration section

Syntax:

```text
/show section:channels
/show section:pings
/show section:auto_replies
/show section:users
/show section:permissions
```

Parameters:

- `section`
  - one of:
    - `channels`
    - `pings`
    - `auto_replies`
    - `users`
    - `permissions`

Behavior:

- `pings` includes both normal pings and regex-mode rules
- `auto_replies` includes both pattern-bound replies and live/offline channel-event replies
- rules are shown in descending priority order
- IDs shown here are the IDs used by `/ping ...` and `/reply ...`
- when one section exceeds Discord's embed size limit, `/show` splits it across
  multiple pages and adds `Previous` and `Next` buttons plus a `Page x/y`
  footer
