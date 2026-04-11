# Adding Commands

This document explains how to add a new Discord feature to the bot after the Discord adapter refactor.

The goal of the current structure is:

- each Discord command area lives in its own file
- the Discord adapter is only the transport layer
- the event bus carries typed events from adapter to service
- services contain business logic
- repositories hide database details
- adding a new feature should feel like adding one new vertical slice instead of editing one giant file

This guide uses a **fictional example feature** named `nickname`.

The example command is:

```text
/nickname add twitch_name:<twitch-name> nickname:<nickname>
```

The feature is **not implemented** in the bot. This document only shows how you would implement it.

## Current Discord Structure

After the refactor, the Discord adapter is split like this:

```text
src/adapters/discord/
  __init__.py
  adapter.py
  client.py
  dispatch.py
  helpers.py
  modals.py
  commands/
    __init__.py
    thread_commands.py
    channel_commands.py
    pattern_commands.py
    account_commands.py
    reply_commands.py
    show_commands.py
```

Responsibilities:

- `adapter.py`
  Wraps the Discord client lifecycle and outbound notifications.
- `client.py`
  Creates the Discord client and registers command modules.
- `dispatch.py`
  Contains small helper functions that publish typed events onto the event bus.
- `helpers.py`
  Shared utility code like standardized responses and CSV parsing.
- `modals.py`
  Shared Discord modals.
- `commands/*.py`
  One file per command area. This is the main extension point for new commands.

That means a new feature usually gets:

- a new command file in `src/adapters/discord/commands/`
- a new event in `src/events/event_types.py`
- a new dispatch helper in `src/adapters/discord/dispatch.py`
- a new service in `src/services/`
- possibly new DB schema and repository code in `src/database/`
- one line of wiring in `src/main.py`

## The Full Flow

For almost every Discord feature, the request path should look like this:

1. Discord slash command is executed.
2. The command callback lives in `src/adapters/discord/commands/<feature>_commands.py`.
3. The callback converts Discord input into clean application data.
4. The callback calls a `dispatch_*` helper from `src/adapters/discord/dispatch.py`.
5. The dispatch helper publishes a typed event into the event bus.
6. A service subscribes to that event in its `__post_init__`.
7. The service validates data and runs business logic.
8. The service uses repositories to read/write the database.
9. The service returns a `DiscordCommandResult` through the event's `result_future`.
10. The command callback sends the result back to Discord as a standardized embed.

In short:

```text
Discord Command
-> commands/*.py
-> dispatch.py
-> EventBus
-> services/*.py
-> database/connection.py repositories
-> DiscordCommandResult
-> commands/*.py
-> Discord embed response
```

## Step 1: Add a New Event Type

If a feature needs its own service, it should usually get its own event.

For the fictional `nickname` feature, add a new event type in:

[`src/events/event_types.py`](../src/events/event_types.py)

Example:

```python
class EventType(StrEnum):
    DISCORD_NICKNAME_REQUESTED = "discord.nickname.requested"
```

Then add a typed payload:

```python
@dataclass(slots=True, frozen=True)
class DiscordNicknameRequestedEvent:
    """Normalized command event for nickname add/remove/update requests."""

    discord_channel_id: int
    requester_id: int
    action: str
    twitch_login: str
    nickname: str | None
    result_future: Future[DiscordCommandResult]
```

Why this is important:

- the adapter can stay dumb
- the service gets already-normalized data
- the event bus stays explicit and typed

## Step 2: Add a Dispatch Helper

Every command module should ideally call a small dispatch helper instead of publishing raw events itself.

Add this to:

[`src/adapters/discord/dispatch.py`](../src/adapters/discord/dispatch.py)

Example:

```python
async def dispatch_nickname_command(
    event_bus: EventBus,
    *,
    discord_channel_id: int,
    requester_id: int,
    action: str,
    twitch_login: str,
    nickname: str | None,
) -> DiscordCommandResult:
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[DiscordCommandResult] = loop.create_future()
    await event_bus.publish(
        EventType.DISCORD_NICKNAME_REQUESTED,
        DiscordNicknameRequestedEvent(
            discord_channel_id=discord_channel_id,
            requester_id=requester_id,
            action=action,
            twitch_login=twitch_login,
            nickname=nickname,
            result_future=result_future,
        ),
    )
    return await result_future
```

Why keep this in a separate helper:

- all command files use the same pattern
- the Discord callback stays short
- event construction is centralized

## Step 3: Add a Command File

Create a new command module:

```text
src/adapters/discord/commands/nickname_commands.py
```

The file should:

- register one command group or one top-level command
- convert Discord parameters into the normalized app shape
- call the new `dispatch_nickname_command(...)`
- return the `DiscordCommandResult` via `send_initial_result(...)`

Example:

```python
from __future__ import annotations

import logging

import discord
from discord import app_commands

from src.events.event_bus import EventBus

from ..dispatch import dispatch_nickname_command
from ..helpers import command_unavailable_result, normalize_optional_text, send_initial_result

logger = logging.getLogger(__name__)


def register_nickname_commands(tree: discord.app_commands.CommandTree, event_bus: EventBus) -> None:
    nickname_group = app_commands.Group(name="nickname", description="Manage Twitch nicknames.")

    @nickname_group.command(name="add", description="Save a nickname for a Twitch user.")
    @app_commands.describe(
        twitch_name="The Twitch login to rename.",
        nickname="The nickname to store and later show in Discord embeds.",
    )
    async def nickname_add(
        interaction: discord.Interaction,
        twitch_name: str,
        nickname: str,
    ) -> None:
        if interaction.channel_id is None:
            await send_initial_result(interaction, command_unavailable_result())
            return

        logger.debug(
            "Discord nickname add discord_channel_id=%s requester_id=%s twitch_name=%s nickname=%r",
            interaction.channel_id,
            interaction.user.id,
            twitch_name,
            nickname,
        )

        result = await dispatch_nickname_command(
            event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
            action="add",
            twitch_login=twitch_name,
            nickname=normalize_optional_text(nickname),
        )
        await send_initial_result(interaction, result)

    tree.add_command(nickname_group)
```

## Step 4: Register the Command File

Import the new registrar in:

[`src/adapters/discord/commands/__init__.py`](../src/adapters/discord/commands/__init__.py)

Example:

```python
from .nickname_commands import register_nickname_commands
```

And export it in `__all__`.

Then call it from:

[`src/adapters/discord/client.py`](../src/adapters/discord/client.py)

Example:

```python
register_nickname_commands(self.tree, self._event_bus)
```

That is the only place where the Discord client needs to know the new command module exists.

## Step 5: Add the Database Model

If the feature stores data, design the schema first.

For `nickname`, a clean minimal table could be:

```sql
CREATE TABLE nickname (
    thread_id       INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    twitch_user_id  TEXT NOT NULL,
    nickname        TEXT NOT NULL,
    PRIMARY KEY (thread_id, twitch_user_id)
);
```

Why this schema:

- nicknames belong to one Discord configuration root
- the same Twitch user can have different nicknames in different Discord contexts
- deleting the Discord context automatically deletes nicknames too

You would add that to:

[`src/database/schema.sql`](../src/database/schema.sql)

## Step 6: Add Repository Types

Add a record type to:

[`src/database/connection.py`](../src/database/connection.py)

Example:

```python
@dataclass(slots=True, frozen=True)
class NicknameRecord:
    thread_id: int
    twitch_user_id: str
    nickname: str
```

Then add a repository interface:

```python
class NicknameRepository:
    def get_by_thread_and_user_id(self, thread_id: int, twitch_user_id: str) -> NicknameRecord | None:
        raise NotImplementedError

    def upsert_nickname(self, *, thread_id: int, twitch_user_id: str, nickname: str) -> NicknameRecord:
        raise NotImplementedError

    def remove_nickname(self, *, thread_id: int, twitch_user_id: str) -> NicknameRecord | None:
        raise NotImplementedError
```

Then implement the Postgres version:

```python
@dataclass(slots=True)
class PostgresNicknameRepository(NicknameRepository):
    database: PostgresDatabase

    def get_by_thread_and_user_id(self, thread_id: int, twitch_user_id: str) -> NicknameRecord | None:
        ...

    def upsert_nickname(self, *, thread_id: int, twitch_user_id: str, nickname: str) -> NicknameRecord:
        ...

    def remove_nickname(self, *, thread_id: int, twitch_user_id: str) -> NicknameRecord | None:
        ...
```

## Step 7: Create the Service

Create a new service file:

```text
src/services/nickname_service.py
```

This file is where the actual business logic belongs.

Example structure:

```python
from __future__ import annotations

from dataclasses import dataclass
import logging

from src.adapters.twitch_api import TwitchAPIClient, TwitchAPIError, TwitchChannelNotFoundError
from src.database.connection import NicknameRepository, ThreadRepository, ThreadRecord
from src.events.event_bus import EventBus
from src.events.event_types import (
    DiscordCommandResult,
    DiscordNicknameRequestedEvent,
    DiscordResultStyle,
    EventType,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NicknameCommandService:
    event_bus: EventBus
    thread_repository: ThreadRepository
    nickname_repository: NicknameRepository
    twitch_api: TwitchAPIClient

    def __post_init__(self) -> None:
        self.event_bus.subscribe(EventType.DISCORD_NICKNAME_REQUESTED, self.handle_request)

    async def handle_request(self, event: DiscordNicknameRequestedEvent) -> None:
        try:
            result = await self._handle_action(event)
        except TwitchChannelNotFoundError as error:
            result = DiscordCommandResult(
                title="Validation Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except TwitchAPIError as error:
            result = DiscordCommandResult(
                title="Twitch API Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Unexpected error while handling nickname command.")
            result = DiscordCommandResult(
                title="Unexpected Error",
                message=str(error),
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )

        if not event.result_future.done():
            event.result_future.set_result(result)

    async def _handle_action(self, event: DiscordNicknameRequestedEvent) -> DiscordCommandResult:
        thread = self._ensure_thread_owner(event.discord_channel_id, event.requester_id)
        if isinstance(thread, DiscordCommandResult):
            return thread

        twitch_user = await self.twitch_api.get_user_by_login(event.twitch_login)

        if event.action == "add":
            if not event.nickname:
                return DiscordCommandResult(
                    title="Validation Error",
                    message="Please provide a nickname.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )

            record = self.nickname_repository.upsert_nickname(
                thread_id=thread.thread_id,
                twitch_user_id=twitch_user.user_id,
                nickname=event.nickname,
            )
            return DiscordCommandResult(
                title="Nickname Saved",
                message=f"Saved nickname `{record.nickname}` for `{twitch_user.display_name}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        if event.action == "remove":
            removed = self.nickname_repository.remove_nickname(
                thread_id=thread.thread_id,
                twitch_user_id=twitch_user.user_id,
            )
            if removed is None:
                return DiscordCommandResult(
                    title="Not Found",
                    message="No nickname exists for that Twitch user in this Discord context.",
                    style=DiscordResultStyle.ERROR,
                    ephemeral=True,
                )
            return DiscordCommandResult(
                title="Nickname Removed",
                message=f"Removed nickname for `{twitch_user.display_name}`.",
                style=DiscordResultStyle.SUCCESS,
                ephemeral=False,
            )

        raise ValueError("Unsupported nickname action.")

    def _ensure_thread_owner(self, discord_channel_id: int, requester_id: int) -> ThreadRecord | DiscordCommandResult:
        thread = self.thread_repository.get_by_discord_channel_id(discord_channel_id)
        if thread is None:
            return DiscordCommandResult(
                title="Not Joined",
                message="This Discord channel is not connected yet. Use `/join` first.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        if thread.owner_id != requester_id:
            return DiscordCommandResult(
                title="Permission Denied",
                message="Only the owner of this Discord channel configuration can change nicknames.",
                style=DiscordResultStyle.ERROR,
                ephemeral=True,
            )
        return thread
```

### Important service rules

A service should:

- subscribe in `__post_init__`
- receive one typed event
- never talk to Discord directly
- return `DiscordCommandResult`
- do all validation here, not in the adapter
- use repositories instead of raw SQL

## Step 8: Wire the Service in `main.py`

Add the repository and service in:

[`src/main.py`](../src/main.py)

Example:

```python
nickname_repository = PostgresNicknameRepository(database)

NicknameCommandService(
    event_bus=event_bus,
    thread_repository=thread_repository,
    nickname_repository=nickname_repository,
    twitch_api=twitch_api,
)
```

If this step is forgotten, the command will register in Discord but no service will answer the event.

That is one of the most common mistakes when adding a new feature.

## Step 9: Optional Modal Support

Some commands are better with slash parameters only.

Example:

```text
/nickname add twitch_name:dancedown nickname:boss
```

That feature does not need a modal.

But if you wanted a modal, the current structure supports that too.

### Where to put modal code

For one-off shared modals:

- [`src/adapters/discord/modals.py`](../src/adapters/discord/modals.py)

For larger features, you can also create a dedicated file:

```text
src/adapters/discord/nickname_modals.py
```

or even:

```text
src/adapters/discord/commands/nickname_modal.py
```

The exact file name is less important than keeping the feature self-contained.

### Example modal

```python
class NicknameModal(discord.ui.Modal, title="Set Nickname"):
    twitch_name = discord.ui.TextInput(label="Twitch Name", required=True)
    nickname = discord.ui.TextInput(label="Nickname", required=True)

    def __init__(self, *, event_bus: EventBus, discord_channel_id: int, requester_id: int) -> None:
        super().__init__(timeout=300)
        self._event_bus = event_bus
        self._discord_channel_id = discord_channel_id
        self._requester_id = requester_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        result = await dispatch_nickname_command(
            self._event_bus,
            discord_channel_id=self._discord_channel_id,
            requester_id=self._requester_id,
            action="add",
            twitch_login=self.twitch_name.value,
            nickname=self.nickname.value,
        )
        await send_initial_result(interaction, result)
```

And then in the command file:

```python
@nickname_group.command(name="modal", description="Open a nickname input dialog.")
async def nickname_modal(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(
        NicknameModal(
            event_bus=event_bus,
            discord_channel_id=interaction.channel_id,
            requester_id=interaction.user.id,
        )
    )
```

### Important modal rule

A modal still should not contain business logic.

The modal should only:

- collect input
- dispatch the same event as a normal slash command
- render the result

The service should not care whether the request came from slash parameters or a modal.

## Step 10: Use the New Data in Existing Features

The user requested this nickname example with one extra behavior:

> if a nickname exists, use it in the pattern message instead of the original nickname

That means a second step beyond the command itself.

The most likely place to apply that would be the tracking path, for example in:

- [`src/services/pattern_service.py`](../src/services/pattern_service.py)
- or a small helper used by `PatternTrackingService`

The cleaner approach is:

1. inject `nickname_repository` into the tracking service
2. before building the embed, look up whether a nickname exists for the author in this thread
3. if a nickname exists, substitute it as the displayed author name
4. keep the original Twitch login and user id unchanged for actual matching logic

Pseudo-example:

```python
nickname = nickname_repository.get_by_thread_and_user_id(
    thread_id=thread.thread_id,
    twitch_user_id=event.author_id,
)

display_name = nickname.nickname if nickname is not None else (event.author_display_name or event.author_login)
```

Then pass `display_name` into the embed builder.

Important:

- matching should still use the real Twitch identity
- the nickname should only affect presentation

## Step 11: Add Tests

A new feature should usually get tests in three places:

1. service tests
2. optional adapter/command tests
3. any downstream feature behavior that changes because of the new data

For `nickname`, a minimal file would likely be:

```text
src/tests/test_nickname_service.py
```

Good tests would be:

- add nickname stores data
- remove nickname deletes data
- command fails when channel is not joined
- command fails for non-owner
- Twitch login is validated
- nickname is used in tracking output if present

## Step 12: Common Mistakes

When adding a new command, these are the most likely breakpoints:

- you added the command file but forgot to register it in `client.py`
- you added the event type but forgot the dispatch helper
- you added the service file but forgot to instantiate it in `main.py`
- you changed the schema but forgot the repository implementation
- the adapter returns raw Discord data instead of normalized application data
- the service tries to send Discord messages directly instead of returning `DiscordCommandResult`
- the modal contains business logic instead of dispatching to the same service path

## Recommended Pattern for New Features

For most new features, follow this checklist:

1. Design the database shape.
2. Add a typed event.
3. Add a dispatch helper.
4. Add a new command file in `src/adapters/discord/commands/`.
5. Add or extend repository code.
6. Add a dedicated service in `src/services/`.
7. Wire it in `src/main.py`.
8. Add tests.
9. Only then add optional modal UX.

That order works well because:

- the service stays independent from Discord UI
- tests can run before you polish UX
- the feature remains modular

## Minimal File List for the Example

If `nickname` were implemented, these are the files you would most likely touch:

```text
src/events/event_types.py
src/adapters/discord/dispatch.py
src/adapters/discord/commands/nickname_commands.py
src/adapters/discord/commands/__init__.py
src/adapters/discord/client.py
src/database/schema.sql
src/database/connection.py
src/services/nickname_service.py
src/services/pattern_service.py
src/main.py
src/tests/test_nickname_service.py
```

Optional modal variant:

```text
src/adapters/discord/modals.py
```

or

```text
src/adapters/discord/commands/nickname_modal.py
```

## Final Rule of Thumb

If you are unsure where code belongs, use this rule:

- `commands/*.py`: parse Discord input and return Discord output
- `dispatch.py`: publish typed events
- `event_types.py`: define the contract
- `services/*.py`: business logic
- `database/connection.py`: persistence details
- `main.py`: wiring
- `modals.py`: input UI only

If a file starts doing two of those jobs, it probably needs to be split.
