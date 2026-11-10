from __future__ import annotations

from uuid import uuid4

import pytest

from src.config import AppConfig
from src.database.postgres import PostgresDatabase, PostgresMigrationRunner, PostgresTwitchUserCacheRepository
from src.services.twitch_user_directory_service import TwitchUserDirectoryService
from src.tests.test_twitch_user_directory_service import FakeTwitchAPI


@pytest.mark.asyncio
async def test_color_batch_persists_across_restart_and_preserves_newer_irc_metadata() -> None:
    database = PostgresDatabase(AppConfig())
    await database.open()
    await PostgresMigrationRunner(database=database).apply_pending()
    repository = PostgresTwitchUserCacheRepository(database)
    user_id = f"color-{uuid4()}"
    login = f"color_{uuid4().hex}"
    try:
        await repository.upsert_from_api(
            twitch_user_id=user_id,
            twitch_login=login,
            display_name="User",
            profile_image_url="https://example.test/avatar.png",
            chat_color=None,
        )
        records = await repository.fill_missing_chat_colors({user_id: "#AA00BB", "nonexistent-color-user": "#000000"})
        assert len(records) == 1
        assert records[0].chat_color == "#AA00BB"
        api = FakeTwitchAPI()
        restarted = TwitchUserDirectoryService(api, repository, memory_cache_size=1)
        assert await restarted.get_user_chat_color_by_id(user_id) == "#AA00BB"
        assert api.color_requests == []

        await repository.observe_from_chat(
            twitch_user_id=user_id,
            twitch_login=login,
            display_name="Updated User",
            chat_color="#123456",
        )
        records = await repository.fill_missing_chat_colors({user_id: "#AA00BB"})
        assert records[0].chat_color == "#123456"
        assert records[0].display_name == "Updated User"
        assert records[0].profile_image_url == "https://example.test/avatar.png"
        refreshed = await repository.upsert_from_api(
            twitch_user_id=user_id,
            twitch_login=login,
            display_name="Updated User",
            profile_image_url="https://example.test/avatar.png",
            chat_color=None,
        )
        assert refreshed.chat_color == "#123456"

        await repository.observe_from_chat(twitch_user_id=user_id, twitch_login=login, display_name="Updated User", chat_color="")
        assert (await repository.fill_missing_chat_colors({user_id: "#AA00BB"}))[0].chat_color == ""
    finally:
        async with database.async_cursor() as cursor:
            await cursor.execute("DELETE FROM twitch_user_cache WHERE twitch_user_id = %s", (user_id,))
        await database.close()
