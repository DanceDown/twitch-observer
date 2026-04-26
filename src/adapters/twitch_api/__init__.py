"""Minimal Twitch API client used for validation and metadata lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp

from src.config import AppConfig


class TwitchAPIError(RuntimeError):
    """Base error for Twitch API integration problems."""


class TwitchAPIConfigurationError(TwitchAPIError):
    """Raised when the Twitch API client credentials are missing."""


class TwitchChannelNotFoundError(TwitchAPIError):
    """Raised when a Twitch login does not resolve to a real channel/user."""


class TwitchAuthenticationError(TwitchAPIError):
    """Raised when a user access token is invalid or insufficient."""


class TwitchDeviceFlowError(TwitchAPIError):
    """Raised for fatal Device Code Flow problems."""


@dataclass(slots=True, frozen=True)
class TwitchUser:
    """Twitch user data needed by the application."""

    user_id: str
    login: str
    display_name: str
    profile_image_url: str | None = None


@dataclass(slots=True, frozen=True)
class TwitchValidatedToken:
    """Metadata returned by Twitch's token validation endpoint."""

    client_id: str
    login: str
    user_id: str
    scopes: tuple[str, ...]
    expires_in: int
    token_type: str | None = None


@dataclass(slots=True, frozen=True)
class TwitchDeviceCodeStart:
    """Initial Device Code Flow payload returned by Twitch."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(slots=True, frozen=True)
class TwitchUserTokenBundle:
    """User access/refresh token bundle returned after authorization."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: tuple[str, ...]
    token_type: str | None


@dataclass(slots=True, frozen=True)
class TwitchDevicePollResult:
    """Result of polling one pending Device Code Flow authorization."""

    status: str
    token_bundle: TwitchUserTokenBundle | None = None
    interval: int | None = None
    error_message: str | None = None


class TwitchAPIClient:
    """Async Twitch API helper with lightweight app-token caching."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._app_access_token: str | None = None
        self._app_access_token_expires_at: datetime | None = None

    async def start(self) -> None:
        """Create the HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def get_user_by_login(self, login: str) -> TwitchUser:
        """Resolve a Twitch login to a real Twitch user."""
        normalized_login = login.strip().lower()
        if not normalized_login:
            raise TwitchChannelNotFoundError("Please provide a Twitch channel name.")

        await self.start()
        token = await self._get_app_access_token()
        assert self._session is not None

        async with self._session.get(
            f"{self._config.twitch_api_base_url}/users",
            params={"login": normalized_login},
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        data = payload.get("data", [])
        if not data:
            raise TwitchChannelNotFoundError(f"Twitch channel `{normalized_login}` does not exist.")

        user = data[0]
        return TwitchUser(
            user_id=user["id"],
            login=user["login"],
            display_name=user["display_name"],
            profile_image_url=user.get("profile_image_url"),
        )

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        """Resolve a Twitch user ID back to the corresponding user metadata."""
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise TwitchChannelNotFoundError("Please provide a Twitch user ID.")

        await self.start()
        token = await self._get_app_access_token()
        assert self._session is not None

        async with self._session.get(
            f"{self._config.twitch_api_base_url}/users",
            params={"id": normalized_user_id},
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        data = payload.get("data", [])
        if not data:
            raise TwitchChannelNotFoundError(f"Twitch user ID `{normalized_user_id}` does not exist.")

        user = data[0]
        return TwitchUser(
            user_id=user["id"],
            login=user["login"],
            display_name=user["display_name"],
            profile_image_url=user.get("profile_image_url"),
        )

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        """Return the subset of broadcaster IDs that are currently live."""
        normalized_ids = [user_id.strip() for user_id in user_ids if user_id.strip()]
        if not normalized_ids:
            return set()

        await self.start()
        token = await self._get_app_access_token()
        assert self._session is not None

        params: list[tuple[str, str]] = [("user_id", user_id) for user_id in normalized_ids]
        async with self._session.get(
            f"{self._config.twitch_api_base_url}/streams",
            params=params,
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        return {str(item["user_id"]) for item in payload.get("data", [])}

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        """Validate a user token and return the identity/scopes Twitch reports."""
        normalized_token = _normalize_access_token(access_token)
        if not normalized_token:
            raise TwitchAuthenticationError("Please provide a Twitch user access token.")

        await self.start()
        assert self._session is not None
        async with self._session.get(
            f"{self._config.twitch_auth_base_url}/validate",
            headers={"Authorization": f"OAuth {normalized_token}"},
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "The provided Twitch token is invalid.")
            raise TwitchAuthenticationError(message)

        return TwitchValidatedToken(
            client_id=payload["client_id"],
            login=payload["login"],
            user_id=payload["user_id"],
            scopes=tuple(payload.get("scopes", [])),
            expires_in=int(payload.get("expires_in", 0)),
            token_type=payload.get("token_type"),
        )

    async def start_device_code_flow(self, *, scopes: tuple[str, ...]) -> TwitchDeviceCodeStart:
        """Start Twitch's OAuth Device Code Flow for a user login."""
        if not self._config.twitch_client_id:
            raise TwitchAPIConfigurationError("Twitch Device Code Flow requires TWITCH_CLIENT_ID.")

        await self.start()
        assert self._session is not None
        async with self._session.post(
            f"{self._config.twitch_auth_base_url}/device",
            data={
                "client_id": self._config.twitch_client_id,
                "scopes": " ".join(scopes),
            },
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Could not start the Twitch device login.")
            raise TwitchDeviceFlowError(message)

        return TwitchDeviceCodeStart(
            device_code=payload["device_code"],
            user_code=payload["user_code"],
            verification_uri=payload["verification_uri"],
            expires_in=int(payload["expires_in"]),
            interval=int(payload["interval"]),
        )

    async def poll_device_code_flow(
        self,
        *,
        device_code: str,
        scopes: tuple[str, ...],
    ) -> TwitchDevicePollResult:
        """Poll Twitch for a completed Device Code Flow authorization."""
        if not self._config.twitch_client_id:
            raise TwitchAPIConfigurationError("Twitch Device Code Flow requires TWITCH_CLIENT_ID.")

        await self.start()
        assert self._session is not None
        async with self._session.post(
            f"{self._config.twitch_auth_base_url}/token",
            data={
                "client_id": self._config.twitch_client_id,
                "scopes": " ".join(scopes),
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        ) as response:
            payload = await response.json()

        if response.status < 400:
            return TwitchDevicePollResult(
                status="success",
                token_bundle=TwitchUserTokenBundle(
                    access_token=payload["access_token"],
                    refresh_token=payload.get("refresh_token"),
                    expires_in=int(payload.get("expires_in", 0)),
                    scope=tuple(payload.get("scope", [])),
                    token_type=payload.get("token_type"),
                ),
            )

        message = payload.get("message", "device_flow_error")
        if message == "authorization_pending":
            return TwitchDevicePollResult(status="pending")
        if message == "slow_down":
            return TwitchDevicePollResult(
                status="slow_down",
                interval=self._config.twitch_device_flow_slowdown_step_seconds,
            )
        if message in {"access_denied", "invalid device code", "expired_token"}:
            return TwitchDevicePollResult(status="failed", error_message=message)
        raise TwitchDeviceFlowError(message)

    async def refresh_user_access_token(self, refresh_token: str) -> TwitchUserTokenBundle:
        """Refresh a user access token using Twitch's refresh-token flow."""
        if not self._config.twitch_client_id:
            raise TwitchAPIConfigurationError("Refreshing a Twitch token requires TWITCH_CLIENT_ID.")

        normalized_refresh_token = refresh_token.strip()
        if not normalized_refresh_token:
            raise TwitchAuthenticationError("Missing Twitch refresh token.")

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": normalized_refresh_token,
            "client_id": self._config.twitch_client_id,
        }
        if self._config.twitch_client_secret:
            form_data["client_secret"] = self._config.twitch_client_secret

        await self.start()
        assert self._session is not None
        async with self._session.post(
            f"{self._config.twitch_auth_base_url}/token",
            data=form_data,
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Could not refresh the Twitch access token.")
            raise TwitchAuthenticationError(message)

        return TwitchUserTokenBundle(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=int(payload.get("expires_in", 0)),
            scope=tuple(payload.get("scope", [])),
            token_type=payload.get("token_type"),
        )

    async def send_chat_message(
        self,
        *,
        access_token: str,
        client_id: str,
        sender_id: str,
        broadcaster_id: str,
        message: str,
        reply_parent_message_id: str | None = None,
    ) -> str:
        """Send a chat message through Twitch's Send Chat Message API."""
        normalized_token = _normalize_access_token(access_token)
        if not normalized_token:
            raise TwitchAuthenticationError("Missing linked Twitch access token.")

        await self.start()
        assert self._session is not None
        request_body: dict[str, str] = {
            "broadcaster_id": broadcaster_id,
            "sender_id": sender_id,
            "message": message,
        }
        if reply_parent_message_id:
            request_body["reply_parent_message_id"] = reply_parent_message_id

        async with self._session.post(
            f"{self._config.twitch_api_base_url}/chat/messages",
            headers={
                "Client-Id": client_id,
                "Authorization": f"Bearer {normalized_token}",
                "Content-Type": "application/json",
            },
            json=request_body,
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message_text = payload.get("message", "Could not send the Twitch chat message.")
            if response.status in {401, 403}:
                raise TwitchAuthenticationError(message_text)
            raise TwitchAPIError(message_text)

        data = payload.get("data", [])
        if not data:
            raise TwitchAPIError("Twitch did not return a send result.")
        result = data[0]
        if not result.get("is_sent", False):
            drop_reason = result.get("drop_reason") or {}
            raise TwitchAPIError(drop_reason.get("message", "Twitch dropped the chat message."))
        return str(result["message_id"])

    async def _get_app_access_token(self) -> str:
        if not self._config.twitch_client_id or not self._config.twitch_client_secret:
            raise TwitchAPIConfigurationError("Twitch API validation requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET.")

        now = datetime.now(UTC)
        if self._app_access_token is not None and self._app_access_token_expires_at is not None and now < self._app_access_token_expires_at:
            return self._app_access_token

        await self.start()
        assert self._session is not None
        async with self._session.post(
            f"{self._config.twitch_auth_base_url}/token",
            params={
                "client_id": self._config.twitch_client_id,
                "client_secret": self._config.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        ) as response:
            payload = await response.json()

        if response.status >= 400:
            message = payload.get("message", "Could not authenticate against Twitch.")
            raise TwitchAPIError(message)

        self._app_access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 0))
        self._app_access_token_expires_at = now + timedelta(
            seconds=max(0, expires_in - self._config.twitch_app_access_token_refresh_skew_seconds)
        )
        return self._app_access_token


def _normalize_access_token(access_token: str) -> str:
    """Normalize access tokens pasted from sources like Chatterino."""
    normalized = access_token.strip()
    if normalized.lower().startswith("oauth:"):
        normalized = normalized[6:]
    return normalized

