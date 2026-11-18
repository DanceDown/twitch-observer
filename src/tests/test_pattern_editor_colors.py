from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import discord
import pytest

from src.config import AppConfig
from src.database.postgres import PostgresChannelRepository, PostgresDatabase, PostgresPatternRepository, PostgresThreadRepository
from src.database.records import PatternCreate, PatternDefinition
from src.entrypoints.discord.ui.patterns.basics_modal import PatternBasicsModal
from src.entrypoints.discord.ui.patterns.context import PatternViewContext
from src.entrypoints.discord.ui.patterns.selection import PatternPickerView
from src.events.discord_results import DiscordResultStyle
from src.localization import Localizer
from src.services.patterns import PatternCommandService
from src.tests.test_discord_ui_prefill import (
    _FakeModalSubmitInteraction,
    _FakePatternProvider,
    _fake_services,
    _pattern_presentation,
)
from src.tests.test_pattern_service import FakeTwitchAPI


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_color", "submitted_color", "expected_color"),
    [
        ("#ffffff", "", None),
        ("#ffffff", "  ", None),
        ("#ffffff", "#123456", "#123456"),
        ("#ffffff", "#ffffff", "#ffffff"),
        (None, "", None),
        (None, "#ffffff", "#ffffff"),
    ],
)
async def test_editor_color_submission_persists_and_reopens(
    monkeypatch: pytest.MonkeyPatch,
    initial_color: str | None,
    submitted_color: str,
    expected_color: str | None,
) -> None:
    database = PostgresDatabase(AppConfig())
    await database.open()
    thread_repository = PostgresThreadRepository(database)
    pattern_repository = PostgresPatternRepository(database)
    discord_channel_id = 900_000_000_000 + uuid4().int % 1_000_000_000
    localizer = Localizer.from_directory()
    try:
        thread = await thread_repository.create(owner_id=200, discord_channel_id=discord_channel_id)
        pattern = await pattern_repository.add_pattern(
            PatternCreate(
                thread_id=thread.thread_id,
                definition=PatternDefinition("hello", "all_tracked", (), "all_users", (), "all", "both", False, False),
                color=initial_color,
                disabled=False,
                priority=0,
            )
        )
        assert pattern.color == initial_color
        provider = _FakePatternProvider(patterns=[replace(_pattern_presentation(pattern.pattern_id), pattern=pattern)])
        services = _fake_services()
        services.pattern = PatternCommandService(
            thread_repository=thread_repository,
            channel_repository=PostgresChannelRepository(database),
            pattern_repository=pattern_repository,
            twitch_api=FakeTwitchAPI(),
            localizer=localizer,
        )
        context = PatternViewContext(
            owner_id=200,
            language="german",
            services=services,
            data_provider=provider,
            discord_channel_id=discord_channel_id,
            localizer=localizer,
        )
        interaction = _FakeModalSubmitInteraction(channel_id=discord_channel_id)
        picker = PatternPickerView(context=context)
        await picker.submit_selection(cast(discord.Interaction, interaction), pattern.pattern_id)
        editor = interaction.response.sent_view
        assert editor.state.color == initial_color
        modal = PatternBasicsModal(parent=editor)
        assert modal.color.default == initial_color
        modal.pattern_text._refresh_state(interaction, {"value": pattern.regex})
        modal.color._refresh_state(interaction, {"value": submitted_color})
        modal.mode.component._handle_submit(interaction, {"value": "ping"}, {})
        modal.case_sensitive.component._handle_submit(interaction, {"values": []}, {})
        monkeypatch.setattr("src.entrypoints.discord.ui.patterns.basics_modal.defer_interaction_response", AsyncMock())
        await modal.on_submit(cast(discord.Interaction, interaction))
        assert editor.state.color == expected_color

        monkeypatch.setattr(editor, "ensure_step_allowed", AsyncMock(return_value=True))
        monkeypatch.setattr(editor, "finish_with_interaction", AsyncMock())
        monkeypatch.setattr("src.entrypoints.discord.ui.patterns.home.defer_interaction_response", AsyncMock())
        await editor.save.callback(SimpleNamespace(user=SimpleNamespace(id=200)))
        result = editor.finish_with_interaction.await_args.args[1]
        assert result.style == DiscordResultStyle.SUCCESS
        if initial_color != expected_color:
            # Check that a change is reported without tying the test to localized wording.
            assert len(result.message.splitlines()) > 1

        stored = await pattern_repository.get_pattern_by_id(thread_id=thread.thread_id, pattern_id=pattern.pattern_id)
        assert stored is not None
        assert stored.color == expected_color
        async with database.read_cursor() as cursor:
            await cursor.execute(
                "SELECT color FROM pattern WHERE thread_id = %s AND pattern_id = %s", (thread.thread_id, pattern.pattern_id)
            )
            assert await cursor.fetchone() == (expected_color,)
        provider.patterns = [replace(provider.patterns[0], pattern=stored)]
        reopened = _FakeModalSubmitInteraction(channel_id=discord_channel_id)
        await picker.submit_selection(cast(discord.Interaction, reopened), pattern.pattern_id)
        assert reopened.response.sent_view.state.color == expected_color
        assert PatternBasicsModal(parent=reopened.response.sent_view).color.default == expected_color
    finally:
        async with database.async_cursor() as cursor:
            await cursor.execute("DELETE FROM thread WHERE discord_channel_id = %s", (discord_channel_id,))
        await database.close()
