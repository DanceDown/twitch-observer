# Twitch IRC Notes

This document explains the anonymous Twitch IRC path used as the read-only chat
adapter.

## Why IRC exists here

The project wants to read public Twitch chat as anonymously as possible.
For that goal, anonymous Twitch IRC is a better fit than EventSub chat intake,
because EventSub chat subscriptions require authenticated access.

Important:

- IRC is the chat-message intake path
- live/offline state is tracked separately through batched Helix `Get Streams`
  polling with the application's Twitch client credentials

The application architecture keeps this in a runtime entrypoint so that the
read path can be replaced or extended later.

## Raw Twitch IRC Message Example

This is a simplified but realistic `PRIVMSG` line:

```text
@badge-info=;badges=;color=#1E90FF;display-name=TestUser;emotes=;id=abc123;reply-parent-msg-id=def456;room-id=999;user-id=777;tmi-sent-ts=1710000000000 :testuser!testuser@testuser.tmi.twitch.tv PRIVMSG #example :Hello world!
```

## How to read the line

### 1. Tags

The line starts with `@...` and contains semicolon-separated metadata:

```text
@badge-info=;badges=;color=#1E90FF;display-name=TestUser;id=abc123;reply-parent-msg-id=def456;room-id=999;user-id=777;tmi-sent-ts=1710000000000
```

Useful Twitch tags include:

- `display-name`: visible display name
- `id`: unique message id
- `reply-parent-msg-id`: parent message id for replies
- `room-id`: broadcaster / room id
- `user-id`: sender id
- `tmi-sent-ts`: timestamp in milliseconds
- `color`: user color in chat

### 2. Prefix

The prefix identifies the sender at IRC protocol level:

```text
:testuser!testuser@testuser.tmi.twitch.tv
```

The nick before `!` is the Twitch login name:

```text
testuser
```

### 3. Command

The command tells us what kind of IRC message this is:

```text
PRIVMSG
```

For the observer, `PRIVMSG` is the important case because it represents a chat message.

### 4. Parameters

The first parameter is the channel:

```text
#example
```

The application normalizes this to:

```text
example
```

### 5. Trailing payload

Everything after the final ` :` is the actual message text:

```text
Hello world!
```

## How the application maps this

The adapter converts the raw IRC line into a normalized event with fields such as:

```text
channel_login=example
author_login=testuser
author_display_name=TestUser
content=Hello world!
message_id=abc123
broadcaster_id=999
author_id=777
reply_parent_message_id=def456
```

That normalized event is then passed directly into the chat processing
pipeline.

## Anonymous login shape

The anonymous adapter connects with a generated nick such as:

```text
justinfan482193
```

It requests Twitch IRC capabilities for tags and commands, joins the configured channels,
and answers server `PING` messages with `PONG`.

## Connection handshake

After the TCP/TLS connection opens, the adapter sends:

```text
PASS SCHMOOPIIE
CAP REQ :twitch.tv/tags twitch.tv/commands
NICK justinfan482193
USER justinfan482193 8 * :justinfan482193
```

### `PASS SCHMOOPIIE`

This is the traditional anonymous Twitch IRC password used for guest-style
read-only connections.

Even though this is not a real secret for anonymous mode, Twitch IRC
expects the client to send a `PASS` line as part of the registration handshake.
Without it, channel joins and message delivery can fail even if the socket
itself was opened successfully.

### `CAP REQ :twitch.tv/tags twitch.tv/commands`

This asks Twitch IRC to enable extra capabilities.

- `twitch.tv/tags` enables metadata such as `display-name`, `user-id`, `room-id`, `id`, and `tmi-sent-ts`
- `twitch.tv/commands` enables additional Twitch-specific IRC command handling

Without tags, the observer would lose a lot of useful structured metadata.

### `NICK justinfan482193`

This sets the IRC nickname used for the anonymous session.

The nick follows the traditional anonymous Twitch IRC style:

```text
justinfan<random_number>
```

The random suffix avoids collisions with other anonymous connections and matches the long-standing anonymous IRC convention.

### `USER justinfan482193 8 * :justinfan482193`

This is a standard IRC registration line.

It finishes the client registration handshake together with `NICK`. For our use case, the important part is not the exact `8 *` value, but that the client completes a normal IRC login sequence so Twitch accepts the connection.

## Joining channels

Channels can be joined immediately after startup or later at runtime.

Example:

```text
JOIN #example
JOIN #second
```

The adapter normalizes user input before sending the command:

- strips whitespace
- removes a leading `#` if present
- lowercases the channel login
- avoids duplicate joins

This is important because channels will later be managed dynamically through Discord commands, not only through the startup configuration.

## Ping / Pong

Twitch IRC keeps the connection alive with server ping messages.

Example:

```text
PING :tmi.twitch.tv
```

The adapter answers with:

```text
PONG :tmi.twitch.tv
```

If the client stops answering `PING`, Twitch will eventually close the connection.
