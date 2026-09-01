from __future__ import annotations

import pytest

from src.config import AppConfig
from src.gateways.twitch_api import TwitchAPIClient

RecordedRequest = tuple[str, str, dict[str, object]]


class RecordingTwitchAPIClient(TwitchAPIClient):
    def __init__(self) -> None:
        super().__init__(
            AppConfig(
                twitch_client_id="client-id",
                twitch_client_secret="client-secret",
                twitch_api_base_url="https://api.example.test/helix",
            )
        )
        self.requests: list[RecordedRequest] = []

    async def start(self) -> None:
        return None

    async def _get_app_access_token(self) -> str:
        return "app-token"

    async def _request_json(self, method: str, url: str, **kwargs: object) -> tuple[int, dict[str, object]]:
        self.requests.append((method, url, kwargs))
        if url.endswith("/users"):
            return 200, {
                "data": [
                    {
                        "id": "42",
                        "login": "example",
                        "display_name": "Example",
                        "profile_image_url": "https://example.test/avatar.png",
                    }
                ]
            }
        if url.endswith("/chat/color"):
            return 200, {"data": [{"user_id": "42", "color": "#AA00BB"}]}
        raise AssertionError(f"Unexpected Twitch API URL: {url}")


@pytest.mark.asyncio
async def test_get_users_by_ids_does_not_fetch_twitch_chat_color_by_default() -> None:
    client = RecordingTwitchAPIClient()

    users = await client.get_users_by_ids(("42",))

    assert len(users) == 1
    assert users[0].chat_color is None
    assert [url for _method, url, _kwargs in client.requests] == [
        "https://api.example.test/helix/users",
    ]


@pytest.mark.asyncio
async def test_get_users_by_ids_with_chat_colors_attaches_twitch_chat_color() -> None:
    client = RecordingTwitchAPIClient()

    users = await client.get_users_by_ids_with_chat_colors(("42",))

    assert len(users) == 1
    assert users[0].chat_color == "#AA00BB"
    assert [url for _method, url, _kwargs in client.requests] == [
        "https://api.example.test/helix/users",
        "https://api.example.test/helix/chat/color",
    ]
    color_request = client.requests[1][2]
    assert color_request["params"] == [("user_id", "42")]
