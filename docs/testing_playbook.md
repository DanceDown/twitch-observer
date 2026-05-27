# Testing and QA Playbook

This guide explains how to test the full Twitch Observer feature set from two angles:

1. code-level tests (what is covered, how to run),
2. manual user-facing validation (how to see each feature and each message family in Discord/Twitch).

It is written against the codebase structure (`src/bootstrap/application.py`, `src/services/*`, `src/entrypoints/discord/*`) and the localized message catalog (`lang/*.json`).

## 1) Test Environment Setup

## 1.1 Prerequisites

- Docker Desktop (running)
- Discord test server with at least:
  - one channel where the bot can post,
  - one additional channel/thread for cross-context checks,
  - two Discord users (Owner and Helper)
- Twitch app credentials (`TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`)
- Discord bot credentials (`DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`)

## 1.2 Environment file

1. Copy `.env.example` to `.env`.
2. Fill Discord and Twitch credentials.
3. Keep `LOG_LEVEL=DEBUG` while testing.

## 1.3 Build image with dev dependencies

`ruff` lives in `requirements-dev.txt`, so build the dev dependency variant with `INSTALL_DEV=true`:

```powershell
$env:INSTALL_DEV = "true"
docker compose build app
```

## 2) Code-Side Tests

## 2.1 Full suite

Run all tests:

```powershell
docker compose run --rm app pytest src/tests -q
```

Baseline from a full local suite run:

- `98 passed`

## 2.2 Targeted runs by feature area

```powershell
docker compose run --rm app pytest src/tests/test_channel_command_service.py -q
docker compose run --rm app pytest src/tests/test_pattern_service.py -q
docker compose run --rm app pytest src/tests/test_reply_service.py -q
docker compose run --rm app pytest src/tests/test_write_service.py -q
docker compose run --rm app pytest src/tests/test_permission_service.py -q
docker compose run --rm app pytest src/tests/test_twitch_live_monitor_service.py -q
docker compose run --rm app pytest src/tests/test_twitch_user_directory_service.py -q
docker compose run --rm app pytest src/tests/test_ui_flow_service.py -q
docker compose run --rm app pytest src/tests/test_twitch_irc.py -q
```

## 2.3 Lint and formatting checks

```powershell
docker compose run --rm app ruff check src
docker compose run --rm app ruff format src --check
```

## 2.4 Coverage map (feature -> tests)

- Event bus behavior:
  - `src/tests/test_event_bus.py`
- Discord lifecycle (`/join`, `/leave`, `/on`, `/off`, `/color`, `/language`):
  - `src/tests/test_channel_command_service.py`
- Tracked channel management:
  - `src/tests/test_channel_command_service.py`
- Tracked user management:
  - `src/tests/test_pattern_service.py` (user scope behavior)
  - `src/tests/test_user_command_service.py` is not present; user command behavior is indirectly covered through pattern/reply flows and service wiring
- Ping/pattern CRUD, edit, priority, scopes, filters:
  - `src/tests/test_pattern_service.py`
- Pattern runtime matching and Discord embed emission:
  - `src/tests/test_pattern_service.py`
- Reply command (pattern-bound + event-bound), enable/disable/remove:
  - `src/tests/test_reply_service.py`
- Runtime auto-reply behavior in Twitch:
  - `src/tests/test_reply_service.py`
- Account device flow linking/unlinking:
  - `src/tests/test_reply_service.py`
- Live monitor state transitions and events:
  - `src/tests/test_twitch_live_monitor_service.py`
- IRC parsing and adapter intake:
  - `src/tests/test_twitch_irc.py`
- Twitch user cache directory behavior:
  - `src/tests/test_twitch_user_directory_service.py`
- UI flow guard (not-joined and permission gates):
  - `src/tests/test_ui_flow_service.py`
- Manual `/write` behavior:
  - `src/tests/test_write_service.py`
- Permission grant/revoke behavior:
  - `src/tests/test_permission_service.py`
- Localization details and German umlaut correctness:
  - `src/tests/test_localization.py`
- Show pagination behavior:
  - `src/tests/test_show_ui.py`

## 2.5 Known test gaps (important)

- There is no full end-to-end blackbox test that drives Discord real interactions against the live Discord API.
- Most UI component flows are tested service-first, not widget-first (modals/select states themselves are only partially unit-tested).
- PostgreSQL repository behavior is mostly validated through service tests with fakes/stubs, not by a dedicated repository integration suite.

Because of this, the manual playbook in section 3 is required before release.

## 3) Manual End-to-End Feature Validation

This section is a deterministic script to walk through all user-visible features and message families.

Actors used below:

- **Owner**: user who first runs `/join` in a context
- **Helper**: second user in same Discord context

Test context names:

- **Context A**: main channel/thread for most checks
- **Context B**: second channel/thread for ownership and isolation checks

Recommended Twitch test entities:

- two channels: `channel_a`, `channel_b`
- two users: `user_a`, `user_b`

## 3.1 Pre-join lockout sweep (all commands except `/join`)

Goal: confirm the global not-joined gate works.

In a fresh Discord context, run each command once before `/join`:

1. `/on`
2. `/off`
3. `/color`
4. `/language`
5. `/channel`
6. `/liveping`
7. `/offlineping`
8. `/ping`
9. `/reply`
10. `/account`
11. `/permission`
12. `/write`
13. `/show`
14. `/user`

Expected result:

- command is blocked with the not-joined message family (`results.not_joined.*`) or a command-unavailable gate if context is invalid.

## 3.2 Context lifecycle

1. Owner runs `/join` in Context A.
2. Owner runs `/join` again.
3. Helper runs `/join` in Context A.
4. Owner runs `/off`, then `/off` again.
5. Owner runs `/on`, then `/on` again.
6. Owner runs `/color` and sets `#7788FF`.
7. Owner runs `/color` again and clears color.
8. Owner runs `/language` -> `german`.
9. Helper tries `/language` change without delegated permission.

Expected message families:

- `results.thread.joined.*`
- `results.thread.already_joined.*`
- `results.thread.already_joined_other_owner.*`
- `results.thread.disabled.*`, `results.thread.already_off.*`
- `results.thread.enabled.*`, `results.thread.already_on.*`
- `results.thread.color_updated.*`, `results.thread.color_cleared.*`
- `results.thread.language_updated.*`, `results.thread.language_denied.*`

## 3.3 Channel management

1. In `/channel`, choose **Add**, add `channel_a`.
2. Add `channel_a` again.
3. Add `channel_b`.
4. In `/channel`, choose **Color**, set color for `channel_a`.
5. Clear color for `channel_a`.
6. Remove `channel_b`.

Expected message families:

- `results.channel.added.*`
- `results.channel.already_added.*`
- `results.channel.color_updated.*`
- `results.channel.color_cleared.*`
- `results.channel.removed.*`

Also verify UI-empty states by trying actions in empty configurations:

- `discord.channel_ui.errors.no_channels.*`

## 3.4 Tracked user management

1. In `/user`, add `user_a`.
2. Add `user_a` again.
3. Add `user_b`.
4. Remove `user_b`.

Expected message families:

- `results.user.added.*`
- `results.user.already_added.*`
- `results.user.removed.*`

And UI empty state:

- `discord.user_ui.errors.no_users.*`

## 3.5 Permission model (Owner vs Helper)

1. Helper attempts `/ping` add flow without permission.
2. Owner opens `/permission` and grants Helper:
   - `view`
   - `manage_patterns`
   - `toggle_patterns`
3. Helper retries `/ping` add (should succeed).
4. Owner revokes `manage_patterns` from Helper.
5. Helper retries add (should fail again).
6. Owner clears Helper permissions.

Expected message families:

- `results.permission.granted.*`
- `results.permission.revoked.*`
- `results.permission.cleared.*`
- `results.permission.not_granted.*` / `results.permission.none_found.*`
- permission-denied families under `results.pattern.*`, `results.reply.*`, `results.write.*`, depending on attempted action

## 3.6 Ping/pattern flows

1. Add a normal ping (mode non-regex, basic text).
2. Add a regex ping.
3. Add ping with channel scope = only selected.
4. Add ping with user scope = only selected.
5. Add ping with priority set.
6. Edit one ping: text, mode, color, priority, scopes.
7. Disable one ping, disable again.
8. Enable one ping, enable again.
9. Remove one ping, remove again.

Expected message families:

- `results.pattern.added_title`, `results.pattern.summary.*`
- `results.pattern.updated_title`, `results.pattern.changes.*`
- `results.pattern.disabled_title`, `results.pattern.enabled_title`
- `results.pattern.already_disabled.*`, `results.pattern.already_enabled.*`
- `results.pattern.removed_title`
- `results.pattern.not_found_*`

Validation/UI checks:

- invalid regex -> `results.regex_error.*`
- invalid color/priority -> `results.pattern.invalid_color`, `results.pattern.invalid_priority`, `discord.pattern_ui.errors.invalid_priority.*`
- missing or inconsistent scope selections -> `results.pattern.missing_selected_*`, `results.pattern.unexpected_selected_channels`
- UI no-data states:
  - `discord.pattern_ui.errors.no_pings.*`
  - `discord.pattern_ui.errors.no_enabled.*`
  - `discord.pattern_ui.errors.no_disabled.*`
  - `discord.pattern_ui.errors.no_channels.*`
  - `discord.pattern_ui.errors.no_users.*`

## 3.7 Reply flows (pattern + live/offline events)

Pattern replies:

1. Try adding reply without linked account.
2. Link account (section 3.8), then add pattern reply.
3. Add same reply again (duplicate case).
4. Disable reply, disable again.
5. Enable reply, enable again.
6. Remove reply, remove again.

Event replies:

1. Configure `/liveping` or `/offlineping` trigger first (section 3.9).
2. Add event auto-reply.
3. Disable/enable/remove event auto-reply.

Expected message families:

- `results.reply.no_linked_account.*`
- `results.reply.added_pattern.*`, `results.reply.added_event.*`
- `results.reply.already_exists.*`
- `results.reply.disabled_pattern.*`, `results.reply.enabled_pattern.*`
- `results.reply.disabled_event.*`, `results.reply.enabled_event.*`
- `results.reply.removed_pattern.*`, `results.reply.removed_event.*`
- `results.reply.none_configured.*`, `results.reply.none_configured_event.*`

UI empty-state checks:

- `discord.reply_ui.errors.no_patterns.*`
- `discord.reply_ui.errors.no_event_triggers.*`
- `discord.reply_ui.errors.no_replies.*`

## 3.8 Account linking flow

1. Run `/account` -> **Connect**.
2. Confirm pending code message is shown.
3. Complete Twitch device flow in browser.
4. Verify success notification.
5. Run `/show` and include `Account` section.
6. Run `/account` -> **Disconnect**.
7. Disconnect again.

Expected message families:

- `results.account.finish_login.*` or `results.account.login_pending.*`
- `results.account.linked.*`
- `results.account.unlinked.*`
- `results.account.no_linked_account.*`
- `show.account.*` lines inside `/show`

Failure-path checks (intentionally induced):

- expire device code -> `results.account.login_expired.*`
- deny authorization -> `results.account.login_failed.*`
- missing scope in Twitch token -> `results.account.login_missing_scope.*`

## 3.9 Live/offline notification flow

1. Ensure at least one tracked channel exists.
2. Run `/liveping add` for `channel_a`.
3. Add same live notification again.
4. Disable notification, disable again.
5. Enable notification, enable again.
6. Remove notification, remove again.
7. Add offline notification with `/offlineping add` for `channel_a`, then remove it again.

Expected message families:

- `results.channel_event.notification_added.*`
- `results.channel_event.already_configured.*`
- `results.channel_event.notification_disabled.*`
- `results.channel_event.already_disabled.*`
- `results.channel_event.notification_enabled.*`
- `results.channel_event.already_enabled.*`
- `results.channel_event.notification_removed.*`
- `results.channel_event.none_configured.*`

UI empty-state checks:

- `discord.live_state_ui.errors.no_channels.*`
- `discord.live_state_ui.errors.no_remove_actions.*`
- `discord.live_state_ui.errors.no_disable_actions.*`
- `discord.live_state_ui.errors.no_enable_actions.*`

Runtime event notifications:

When tracked channel transitions state, expect:

- `results.channel_event.went_live.*`
- `results.channel_event.went_offline.*`

## 3.10 Manual Twitch write flow

1. Try `/write` with no tracked channels.
2. Add tracked channel, but keep account unlinked, try `/write`.
3. Link account, send normal message.
4. Send reply message with `reply_to_message_id`.
5. Use Helper without permission and try `/write`.

Expected message families:

- `discord.write_ui.errors.no_channels.*`
- `results.write.no_linked_account.*`
- `results.write.message_sent.*`
- `results.write.reply_sent.*`
- `results.write.permission_denied.*`

Validation checks:

- empty message -> `results.write.empty_message`
- >500 chars -> `results.write.message_too_long`

## 3.11 Show command and pagination

1. Run `/show`, select all sections one by one:
   - `Pings`
   - `Auto-Replies`
   - `Tracked Channels`
   - `Tracked Users`
   - `Permissions`
   - `Account`
2. Confirm each section renders expected content.
3. Create enough data to force pagination, then use `Previous`/`Next`.
4. Let Helper try to click Owner’s paginator buttons.

Expected message families:

- `results.show.overview.*`
- `show.sections.*`
- `show.empty.*` for empty sections
- `discord.show_ui.pagination.footer`
- `discord.show_ui.pagination.locked.*`

## 3.12 Runtime message tracking and auto-reply behavior

1. Keep observer enabled.
2. Send Twitch chat messages in a tracked channel matching and not matching pings.
3. Verify:
   - only matching messages produce Discord tracking embeds,
   - priority chooses highest match,
   - disabled ping does not trigger,
   - pattern with enabled auto-reply suppresses normal tracking embed if designed to do so.
4. Trigger self-reply-loop prevention case and verify no loop.

Primary code-level references for this behavior:

- `src/tests/test_pattern_service.py`
- `src/tests/test_reply_service.py`
- `src/tests/test_message_ingest_service.py`

## 3.13 Leave and cleanup

1. Owner runs `/leave` and confirms modal with `LEAVE`.
2. Verify all context data is gone.
3. Run `/show` and check empty/not-joined behavior.
4. Retry feature commands and confirm not-joined gate.

Expected:

- `results.thread.left.*`
- then same pre-join lockout families from 3.1

## 4) Message Coverage Strategy (Practical)

User-visible messages are split into:

- command results: `results.*`
- UI/form states and lock messages: `discord.*errors.*`, `discord.shared.form_locked.*`, `discord.show_ui.pagination.locked.*`
- show-section content text: `show.*`

For deterministic coverage:

1. complete sections `3.1` to `3.13` in order,
2. use both Owner and Helper,
3. test both empty-state and configured-state paths,
4. test duplicate operations (already exists / already enabled / already disabled),
5. test invalid inputs (regex, priority, message length, missing fields),
6. test one happy path and one denial path for each command family.

This yields complete practical coverage of all user-reachable message families through normal Discord usage.

## 5) Release Gate Recommendation

Before release, require all:

1. `docker compose run --rm app pytest src/tests -q`
2. `docker compose run --rm app ruff check src`
3. manual playbook sections `3.1` to `3.13`

If any manual step fails, capture:

- command used,
- actor (Owner/Helper),
- expected message family key,
- actual embed title/message,
- timestamp and context channel ID.

