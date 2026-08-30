# Command Reference

This is the authoritative command reference for the Discord control surface.

Commands support direct parameters and guided follow-up UI.  
When required action fields are missing, the bot opens the matching modal or flow and keeps provided values prefilled where possible.  
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

### `/help`

Show a beginner-friendly explanation of how to use the bot.

Behavior:

- without a section, it shows the general introduction
- with a section, it jumps directly to one topic
- long help text paginates when needed

Sections:

- `overview`
- `first_steps`
- `channels`
- `users`
- `pings`
- `auto_replies`
- `live_pings`
- `write`
- `account`
- `permissions`
- `tips`

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

The commands below support both direct action parameters and interactive UI flows.  
If you omit the action-specific fields, the bot opens the matching modal or follow-up UI for that action.

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

Subgroups:

- `/reply pattern add|remove|disable|enable`
- `/reply event add|remove|disable|enable`

Behavior:

- pattern-bound replies support message mode and reply-to-message mode
- event-bound replies target configured live/offline triggers
- one pattern has at most one pattern-bound reply

### `/liveping`

Manage live and offline notification triggers for tracked Twitch channels.

Actions:

- `Add`
- `Remove`
- `Color`

Behavior:

- stores event-trigger configuration in adapter-event tables
- `Add` opens one shared modal where the user chooses both the tracked Twitch channel and whether the ping should be `Live` or `Offline`
- `Remove` and `Color` show one combined list of both live and offline pings using the shared displayed IDs
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

### `/support`

Create a support ticket in the configured support Discord channel.

Inputs:

- category: `bug`, `question`, `idea`, or `other`
- title
- description

Behavior:

- requires `SUPPORT_DISCORD_CHANNEL_ID`
- sends a short ephemeral confirmation to the requester
- posts a category-colored ticket embed in the support channel
- ticket actions are `Reply`, `Close`, and `Show`
- `Reply` sends the supporter response back to the original Discord context
- `Close` sends a red close notice back to the original Discord context
- `Show` lets support staff inspect all normal `/show` sections for the original context

### `/show`

Open a UI flow to choose one or more configuration sections to render.

Sections:

- `Pings`
- `Auto-Replies`
- `Live and Offline Pings`
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
