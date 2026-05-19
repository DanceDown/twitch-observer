# Command Reference

This is the authoritative command reference for the Discord control surface.

Root commands open component-driven flows.  
Business actions are selected inside Discord views, selects, and modals.  
All final results are embeds.

## General rules

## Joined context required

Most commands require that the Discord context has been joined first:

```text
/join
```

Without a joined context, guarded commands return `Not Joined`.

## Displayed IDs

Patterns and replies are shown with dense per-thread display numbers in `/show`
and selection UIs.

Important detail:

- those numbers are presentation-only
- interactions carry the stable internal pattern identity behind the scenes
- removing one pattern can renumber later displayed entries

## Command list

## Lifecycle and context commands

### `/join`

Connect the active Discord channel/thread/DM as a configuration root.

### `/leave`

Open a confirmation modal.  
On confirmation, remove saved configuration for the active context.

### `/on`

Enable observer processing for the active context.

### `/off`

Disable observer processing for the active context.

### `/color`

Open a modal to set or clear the default embed color for the active context.

### `/language`

Choose the context language (`english` or `german`).

## Feature commands with form-based actions

The commands below open interactive component flows.  
Actions are selected inside the UI rather than typed manually.

### `/channel`

Manage tracked Twitch channels.

Actions:

- `Add`
- `Remove`
- `Color`

Behavior:

- validates Twitch channel existence on add
- enforces scope safety before removal
- updates IRC membership through service workflow

### `/user`

Manage tracked Twitch users.

Actions:

- `Add`
- `Remove`

### `/ping`

Manage pattern rules (normal ping mode and regex mode).

Actions:

- `Add`
- `Edit`
- `Remove`
- `Disable`
- `Enable`

Supported rule settings:

- pattern text
- match mode (`is_regex`)
- channel scope
- user scope
- subscriber scope
- stream state scope
- case sensitivity
- custom color
- priority (`0`..`9`, optional)

### `/reply`

Manage auto-replies.

Actions:

- `On Ping`
- `On Live Ping`
- `Remove`
- `Disable`
- `Enable`

Behavior:

- pattern-bound replies support message mode and reply-to-message mode
- event-bound replies target configured live/offline triggers
- one pattern has at most one pattern-bound reply

### `/live`

Manage live/offline notification triggers for tracked Twitch channels.

Actions:

- `Add Live Ping`
- `Add Offline Ping`
- `Remove`
- `Disable`
- `Enable`

Behavior:

- stores event-trigger configuration in adapter-event tables
- does not control whether channels are monitored globally

### `/permission`

Manage per-user permissions in the active context.

Actions:

- `Grant`
- `Revoke`
- `Clear`

Available permission names:

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

### `/account`

Manage linked Twitch account for the active context.

Actions:

- `Connect`
- `Disconnect`

Behavior:

- connect flow uses Twitch Device Code Flow
- linked account is used for Twitch writes and auto-replies

### `/write`

Open a modal to send a Twitch chat message using the linked account.

Modal inputs:

- target tracked Twitch channel
- message text
- optional reply target message ID

### `/show`

Open a UI flow to choose one or more configuration sections to render.

Sections:

- `Pings`
- `Auto-Replies`
- `Tracked Channels`
- `Tracked Users`
- `Permissions`
- `Account`

Behavior:

- large results paginate with `Previous` / `Next`
- output includes dense displayed IDs for pattern/reply follow-up choices

## Visibility model

- success results are visible in the active context
- validation and permission failures are typically ephemeral

## Placeholders used in replies

Pattern-bound reply placeholders:

- `{NAME}`
- `{CHANNEL}`
- `{MESSAGE}`

Event-bound reply placeholders:

- `{CHANNEL}`
- `{STATE}`
