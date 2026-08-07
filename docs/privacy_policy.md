# Privacy Policy

Last updated: 2026-08-07

This Privacy Policy applies to the Discord Twitch Observer bot operated by
`DanceDown`.

## What the bot does

The bot connects Discord contexts with Twitch chat. It can track Twitch
channels, observe public Twitch chat, forward matching Twitch messages to
Discord, notify Discord when tracked channels go live or offline, and optionally
send Twitch messages through a Twitch account that a Discord user has linked.

## Data we process

The bot may process these categories of data:

- Discord data: Discord user IDs, channel IDs, thread IDs, DM context IDs,
  command inputs, permission settings, selected language, and display settings
  such as colors.
- Twitch channel and user data: Twitch channel IDs, Twitch user IDs, Twitch
  login names, display names, profile image URLs, live/offline state, and public
  Twitch chat message metadata.
- Twitch chat messages: message IDs, timestamps, Twitch channel IDs, author
  identifiers, usernames, message content, reply references, and bot markers.
- Bot configuration: tracked channels, tracked users, pattern rules, regexes,
  auto-reply text, live/offline action settings, and Discord delivery state.
- Linked Twitch account data: Discord user ID, Twitch user ID, Twitch login,
  OAuth access tokens, refresh tokens, token expiry, token scopes, and Twitch
  application client ID.
- Temporary account-link data: Twitch device flow codes, verification URL,
  expiry, polling status, and last error while an account-link flow is pending.
- Technical data: application logs, error details, database state, and runtime
  configuration needed to operate and secure the service.

The bot does not intentionally collect payment data, government IDs, or special
category data. Users should not put sensitive personal data into commands,
patterns, auto-replies, or Twitch chat messages that the bot can observe.

## Where data comes from

Data is received from:

- Discord, when users run commands, use UI components, or receive bot messages.
- Twitch IRC, when public chat messages are observed in tracked Twitch channels.
- Twitch Helix APIs, when the bot validates users or channels, refreshes cached
  Twitch metadata, checks live state, links Twitch accounts, or sends Twitch
  messages with an authorized linked account.
- Users and administrators, when they configure tracking rules, permissions, and
  auto-replies.

## Why we process data

The bot processes data to:

- provide the requested Discord and Twitch bot features;
- store bot configuration per Discord context;
- match Twitch chat messages against configured rules;
- forward matched messages and live/offline events to Discord;
- send Twitch messages or auto-replies when explicitly configured and
  authorized;
- manage permissions, account linking, and security;
- maintain user metadata caches and reduce unnecessary Twitch API calls;
- debug errors, prevent abuse, and keep the service reliable;
- comply with legal obligations and platform requirements.

## Legal bases

If the GDPR or similar privacy laws apply, the legal bases may include:

- performance of a contract or requested service, when the bot provides features
  requested by users or server administrators;
- consent, when a user links a Twitch account through OAuth and authorizes
  Twitch write actions;
- legitimate interests, for security, abuse prevention, logging, caching,
  reliability, and service improvement;
- legal obligation, when processing is needed to comply with applicable law.

## Sharing data

The bot does not sell personal data.

Data may be shared with:

- Discord, because the bot posts messages, embeds, and command responses there;
- Twitch, because the bot uses Twitch IRC, Twitch Helix APIs, and OAuth flows;
- hosting, database, logging, backup, or infrastructure providers used by the
  operator;
- authorities or third parties when required by law or necessary to protect
  rights, safety, or security.

The public source repository must not contain production secrets, OAuth tokens,
database dumps, or private runtime data.

## International transfers

Discord, Twitch, hosting providers, and other infrastructure providers may
process data in countries outside the user's country or region. The operator is
responsible for choosing providers and transfer safeguards that fit the bot's
deployment and applicable law.

## Retention

The default project does not enforce one universal automatic deletion period for
all database records. Unless the operator configures a shorter retention period:

- Discord context configuration is kept until the context is disabled, deleted,
  or the operator removes it.
- Twitch tracking rules, patterns, permissions, and auto-replies are kept until
  they are changed or deleted.
- Observed Twitch messages are kept while they are needed for matching,
  Discord reply candidates, presence summaries, debugging, or operational
  history.
- Linked Twitch account tokens are kept until the user unlinks the account, the
  operator deletes the account record, authorization is revoked, or the service
  stops operating.
- Pending device-flow records are temporary and expire according to the Twitch
  device-flow response.
- Logs and backups should be retained only as long as needed for security,
  debugging, and recovery.

The bot operator should shorten or delete stored data when it is no longer
needed for the bot.

## Security

The project is designed to keep secrets out of the public repository. Runtime
secrets belong in local environment files or secret managers, not in Git.

The bot stores linked Twitch OAuth tokens in PostgreSQL. The operator should
protect database access, rotate secrets when needed, restrict server access,
use transport encryption where available, and keep dependencies and containers
updated.

No system can be guaranteed perfectly secure. If you believe data was exposed,
use the contact method below.

## User choices and rights

Depending on applicable law, users may have rights to request access,
correction, deletion, restriction, objection, portability, withdrawal of consent,
and information about processing.

To make a privacy request or ask for deletion, use one of these contact methods:

1. Contact DanceDown (user handle: `dancedown`) on Discord (recommended)
2. Send an email to `DanceHere@t-online.de`

Include enough information to identify the relevant Discord user, Discord
context, Twitch account, or Twitch username. The operator may ask for additional
information to verify the request.

Users can also revoke Twitch authorization from their Twitch account settings.
Server administrators can remove bot configuration from Discord using the bot's
commands or by asking the operator.

EU users may also have the right to complain to a data protection authority.

## Children

The bot is not intended for users who are not allowed to use Discord or Twitch
under those platforms' rules. Do not use the bot if you are not permitted to use
the connected platforms.

## Changes

The operator may update this Privacy Policy when the bot, deployment, legal
requirements, or platform requirements change. The updated version should be
published with a new "Last updated" date.

## References

- Discord Developer Terms of Service:
  <https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service>
- Twitch Developer Services Agreement:
  <https://legal.twitch.com/en/legal/developer-agreement/>
- European Commission GDPR information for individuals:
  <https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en>
