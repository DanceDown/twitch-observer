"""Minimal Twitch API client used for validation and metadata lookup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp

from src.config import AppConfig
from src.events.twitch_events import TwitchChatSendRequest

HTTP_ERROR_MIN_STATUS = 400
TWITCH_GET_USERS_MAX_IDS = 100
TWITCH_AUTH_FAILURE_STATUSES = {401, 403}

logger = logging.getLogger(__name__)


class TwitchAPIError(RuntimeError):
    """Base error for Twitch API integration problems."""

    @classmethod
    def get_users_limit_exceeded(cls, max_ids: int) -> TwitchAPIError:
        """Build an error for Helix Get Users requests above Twitch's limit."""
        return cls(f"Twitch Get Users supports at most {max_ids} user IDs per request.")

    @classmethod
    def chat_color_limit_exceeded(cls, max_ids: int) -> TwitchAPIError:
        """Build an error for Helix chat-color requests above Twitch's limit."""
        return cls(f"Twitch Get User Chat Color supports at most {max_ids} user IDs per request.")

    @classmethod
    def send_result_missing(cls) -> TwitchAPIError:
        """Build an error for successful send responses without a result row."""
        return cls("Twitch did not return a send result.")

    @classmethod
    def chat_message_dropped(cls, message: object) -> TwitchAPIError:
        """Build an error for Twitch accepting but dropping a chat message."""
        return cls(str(message))

    @classmethod
    def response_decode_failed(cls, reason: str) -> TwitchAPIError:
        """Build an error for non-error Twitch responses that are not valid JSON."""
        return cls(f"Twitch API response could not be decoded: {reason}")

    @classmethod
    def unexpected_response(cls) -> TwitchAPIError:
        """Build an error for JSON responses with an unexpected root type."""
        return cls("Twitch API returned an unexpected response.")

    @classmethod
    def request_failed(cls, reason: str) -> TwitchAPIError:
        """Build an error for transport-level Twitch request failures."""
        return cls(f"Twitch API request failed: {reason}")


class TwitchAPIConfigurationError(TwitchAPIError):
    """Raised when the Twitch API client credentials are missing."""

    @classmethod
    def device_flow_missing_client_id(cls) -> TwitchAPIConfigurationError:
        """Build an error for Device Code Flow without a configured client ID."""
        return cls("Twitch Device Code Flow requires TWITCH_CLIENT_ID.")

    @classmethod
    def refresh_missing_client_id(cls) -> TwitchAPIConfigurationError:
        """Build an error for refresh-token flow without a configured client ID."""
        return cls("Refreshing a Twitch token requires TWITCH_CLIENT_ID.")

    @classmethod
    def app_credentials_missing(cls) -> TwitchAPIConfigurationError:
        """Build an error for app-token endpoints without client credentials."""
        return cls("Twitch API validation requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET.")


class TwitchChannelNotFoundError(TwitchAPIError):
    """Raised when a Twitch login does not resolve to a real channel/user."""

    @classmethod
    def missing_login(cls) -> TwitchChannelNotFoundError:
        """Build an error for empty Twitch login lookups."""
        return cls("Please provide a Twitch channel name.")

    @classmethod
    def missing_user_id(cls) -> TwitchChannelNotFoundError:
        """Build an error for empty Twitch user-ID lookups."""
        return cls("Please provide a Twitch user ID.")

    @classmethod
    def login_not_found(cls, login: str) -> TwitchChannelNotFoundError:
        """Build an error for Twitch logins that Helix does not return."""
        return cls(f"Twitch channel `{login}` does not exist.")

    @classmethod
    def user_id_not_found(cls, user_id: str) -> TwitchChannelNotFoundError:
        """Build an error for Twitch user IDs that Helix does not return."""
        return cls(f"Twitch user ID `{user_id}` does not exist.")


class TwitchAuthenticationError(TwitchAPIError):
    """Raised when a user access token is invalid or insufficient."""

    @classmethod
    def missing_user_access_token(cls) -> TwitchAuthenticationError:
        """Build an error for token validation without a token."""
        return cls("Please provide a Twitch user access token.")

    @classmethod
    def missing_refresh_token(cls) -> TwitchAuthenticationError:
        """Build an error for refresh-token flow without a refresh token."""
        return cls("Missing Twitch refresh token.")

    @classmethod
    def missing_linked_access_token(cls) -> TwitchAuthenticationError:
        """Build an error for sending through a linked account without a token."""
        return cls("Missing linked Twitch access token.")


class TwitchDeviceFlowError(TwitchAPIError):
    """Raised for fatal Device Code Flow problems."""


class TwitchAPISessionError(TwitchAPIError):
    """Raised when a request is attempted before the HTTP session exists."""

    def __init__(self) -> None:
        """Create the missing-session error with a stable message."""
        super().__init__("Twitch API client session is not started.")


@dataclass(slots=True, frozen=True)
class TwitchUser:
    """Twitch user data needed by the application."""

    user_id: str
    login: str
    display_name: str
    profile_image_url: str | None = None
    chat_color: str | None = None


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
        """Create the client without opening the underlying HTTP session."""
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
        return await self._get_user_by_login(login, include_chat_color=False)

    async def get_user_by_login_with_chat_color(self, login: str) -> TwitchUser:
        """Resolve a Twitch login including the user's Twitch chat-name color."""
        return await self._get_user_by_login(login, include_chat_color=True)

    async def _get_user_by_login(self, login: str, *, include_chat_color: bool) -> TwitchUser:
        normalized_login = login.strip().lower()
        if not normalized_login:
            raise TwitchChannelNotFoundError.missing_login()

        await self.start()
        token = await self._get_app_access_token()
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_api_base_url}/users",
            params={"login": normalized_login},
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        data = payload.get("data", [])
        if not data:
            raise TwitchChannelNotFoundError.login_not_found(normalized_login)

        user = data[0]
        twitch_user = self._build_user(user)
        return await self._with_chat_color(twitch_user) if include_chat_color else twitch_user

    async def get_user_by_id(self, user_id: str) -> TwitchUser:
        """Resolve a Twitch user ID back to the corresponding user metadata."""
        return await self._get_user_by_id(user_id, include_chat_color=False)

    async def get_user_by_id_with_chat_color(self, user_id: str) -> TwitchUser:
        """Resolve a Twitch user ID including the user's Twitch chat-name color."""
        return await self._get_user_by_id(user_id, include_chat_color=True)

    async def _get_user_by_id(self, user_id: str, *, include_chat_color: bool) -> TwitchUser:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise TwitchChannelNotFoundError.missing_user_id()

        await self.start()
        token = await self._get_app_access_token()
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_api_base_url}/users",
            params={"id": normalized_user_id},
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        data = payload.get("data", [])
        if not data:
            raise TwitchChannelNotFoundError.user_id_not_found(normalized_user_id)

        user = data[0]
        twitch_user = self._build_user(user)
        return await self._with_chat_color(twitch_user) if include_chat_color else twitch_user

    async def get_users_by_ids(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Resolve up to 100 Twitch user IDs in one Helix Get Users request."""
        return await self._get_users_by_ids(user_ids, include_chat_color=False)

    async def get_users_by_ids_with_chat_colors(self, user_ids: tuple[str, ...]) -> tuple[TwitchUser, ...]:
        """Resolve up to 100 Twitch users including Twitch chat-name colors."""
        return await self._get_users_by_ids(user_ids, include_chat_color=True)

    async def _get_users_by_ids(self, user_ids: tuple[str, ...], *, include_chat_color: bool) -> tuple[TwitchUser, ...]:
        normalized_user_ids = tuple(user_id.strip() for user_id in user_ids if user_id.strip())
        if not normalized_user_ids:
            return ()
        if len(normalized_user_ids) > TWITCH_GET_USERS_MAX_IDS:
            raise TwitchAPIError.get_users_limit_exceeded(TWITCH_GET_USERS_MAX_IDS)

        await self.start()
        token = await self._get_app_access_token()
        params: list[tuple[str, str]] = [("id", user_id) for user_id in normalized_user_ids]
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_api_base_url}/users",
            params=params,
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        users = tuple(self._build_user(user) for user in payload.get("data", []))
        return await self._with_chat_colors(users) if include_chat_color else users

    async def get_user_chat_colors_by_ids(self, user_ids: tuple[str, ...]) -> dict[str, str]:
        """Return Twitch chat-name colors keyed by user ID."""
        normalized_user_ids = tuple(dict.fromkeys(user_id.strip() for user_id in user_ids if user_id.strip()))
        if not normalized_user_ids:
            return {}
        if len(normalized_user_ids) > TWITCH_GET_USERS_MAX_IDS:
            raise TwitchAPIError.chat_color_limit_exceeded(TWITCH_GET_USERS_MAX_IDS)

        await self.start()
        token = await self._get_app_access_token()
        params: list[tuple[str, str]] = [("user_id", user_id) for user_id in normalized_user_ids]
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_api_base_url}/chat/color",
            params=params,
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Twitch chat color request failed.")
            raise TwitchAPIError(message)

        colors_by_id: dict[str, str] = {}
        for item in payload.get("data", []):
            color = item.get("color")
            colors_by_id[str(item["user_id"])] = color if isinstance(color, str) else ""
        return colors_by_id

    @staticmethod
    def _build_user(user: dict[str, object], *, chat_color: str | None = None) -> TwitchUser:
        profile_image_url = user.get("profile_image_url")
        return TwitchUser(
            user_id=str(user["id"]),
            login=str(user["login"]),
            display_name=str(user["display_name"]),
            profile_image_url=profile_image_url if isinstance(profile_image_url, str) else None,
            chat_color=chat_color,
        )

    async def _with_chat_color(self, user: TwitchUser) -> TwitchUser:
        users = await self._with_chat_colors((user,))
        return users[0] if users else user

    async def _with_chat_colors(self, users: tuple[TwitchUser, ...]) -> tuple[TwitchUser, ...]:
        if not users:
            return ()
        try:
            colors_by_id = await self.get_user_chat_colors_by_ids(tuple(user.user_id for user in users))
        except TwitchAPIError:
            logger.warning("Could not refresh Twitch chat colors for %s user(s).", len(users), exc_info=True)
            return users
        return tuple(
            TwitchUser(
                user_id=user.user_id,
                login=user.login,
                display_name=user.display_name,
                profile_image_url=user.profile_image_url,
                chat_color=colors_by_id.get(user.user_id, user.chat_color),
            )
            for user in users
        )

    async def get_live_user_ids(self, user_ids: list[str]) -> set[str]:
        """Return the subset of broadcaster IDs that are currently live."""
        normalized_ids = [user_id.strip() for user_id in user_ids if user_id.strip()]
        if not normalized_ids:
            return set()

        await self.start()
        token = await self._get_app_access_token()
        params: list[tuple[str, str]] = [("user_id", user_id) for user_id in normalized_ids]
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_api_base_url}/streams",
            params=params,
            headers={
                "Client-Id": self._config.twitch_client_id,
                "Authorization": f"Bearer {token}",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Twitch API request failed.")
            raise TwitchAPIError(message)

        return {str(item["user_id"]) for item in payload.get("data", [])}

    async def validate_user_access_token(self, access_token: str) -> TwitchValidatedToken:
        """Validate a user token and return the identity/scopes Twitch reports."""
        normalized_token = _normalize_access_token(access_token)
        if not normalized_token:
            raise TwitchAuthenticationError.missing_user_access_token()

        await self.start()
        status, payload = await self._request_json(
            "GET",
            f"{self._config.twitch_auth_base_url}/validate",
            headers={"Authorization": f"OAuth {normalized_token}"},
        )

        if status >= HTTP_ERROR_MIN_STATUS:
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
            raise TwitchAPIConfigurationError.device_flow_missing_client_id()

        await self.start()
        status, payload = await self._request_json(
            "POST",
            f"{self._config.twitch_auth_base_url}/device",
            data={
                "client_id": self._config.twitch_client_id,
                "scopes": " ".join(scopes),
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
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
            raise TwitchAPIConfigurationError.device_flow_missing_client_id()

        await self.start()
        status, payload = await self._request_json(
            "POST",
            f"{self._config.twitch_auth_base_url}/token",
            data={
                "client_id": self._config.twitch_client_id,
                "scopes": " ".join(scopes),
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

        if status < HTTP_ERROR_MIN_STATUS:
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
            raise TwitchAPIConfigurationError.refresh_missing_client_id()

        normalized_refresh_token = refresh_token.strip()
        if not normalized_refresh_token:
            raise TwitchAuthenticationError.missing_refresh_token()

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": normalized_refresh_token,
            "client_id": self._config.twitch_client_id,
        }
        if self._config.twitch_client_secret:
            form_data["client_secret"] = self._config.twitch_client_secret

        await self.start()
        status, payload = await self._request_json(
            "POST",
            f"{self._config.twitch_auth_base_url}/token",
            data=form_data,
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Could not refresh the Twitch access token.")
            raise TwitchAuthenticationError(message)

        return TwitchUserTokenBundle(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=int(payload.get("expires_in", 0)),
            scope=tuple(payload.get("scope", [])),
            token_type=payload.get("token_type"),
        )

    async def send_chat_message(self, request: TwitchChatSendRequest) -> str:
        """Send a chat message through Twitch's Send Chat Message API."""
        normalized_token = _normalize_access_token(request.access_token)
        if not normalized_token:
            raise TwitchAuthenticationError.missing_linked_access_token()

        await self.start()
        request_body: dict[str, str] = {
            "broadcaster_id": request.broadcaster_id,
            "sender_id": request.sender_id,
            "message": request.message,
        }
        if request.reply_parent_message_id:
            request_body["reply_parent_message_id"] = request.reply_parent_message_id

        status, payload = await self._request_json(
            "POST",
            f"{self._config.twitch_api_base_url}/chat/messages",
            headers={
                "Client-Id": request.client_id,
                "Authorization": f"Bearer {normalized_token}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message_text = payload.get("message", "Could not send the Twitch chat message.")
            if status in TWITCH_AUTH_FAILURE_STATUSES:
                raise TwitchAuthenticationError(message_text)
            raise TwitchAPIError(message_text)

        data = payload.get("data", [])
        if not data:
            raise TwitchAPIError.send_result_missing()
        result = data[0]
        if not result.get("is_sent", False):
            drop_reason = result.get("drop_reason") or {}
            raise TwitchAPIError.chat_message_dropped(drop_reason.get("message", "Twitch dropped the chat message."))
        return str(result["message_id"])

    async def _get_app_access_token(self) -> str:
        if not self._config.twitch_client_id or not self._config.twitch_client_secret:
            raise TwitchAPIConfigurationError.app_credentials_missing()

        now = datetime.now(UTC)
        if self._app_access_token is not None and self._app_access_token_expires_at is not None and now < self._app_access_token_expires_at:
            return self._app_access_token

        await self.start()
        status, payload = await self._request_json(
            "POST",
            f"{self._config.twitch_auth_base_url}/token",
            params={
                "client_id": self._config.twitch_client_id,
                "client_secret": self._config.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )

        if status >= HTTP_ERROR_MIN_STATUS:
            message = payload.get("message", "Could not authenticate against Twitch.")
            raise TwitchAPIError(message)

        self._app_access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 0))
        self._app_access_token_expires_at = now + timedelta(
            seconds=max(0, expires_in - self._config.twitch_app_access_token_refresh_skew_seconds)
        )
        return self._app_access_token

    async def _request_json(self, method: str, url: str, **kwargs: object) -> tuple[int, dict[str, object]]:
        session = self._require_session()
        request = session.get if method == "GET" else session.post
        try:
            async with request(url, **kwargs) as response:
                try:
                    payload = await response.json()
                except (aiohttp.ClientError, ValueError) as error:
                    if response.status >= HTTP_ERROR_MIN_STATUS:
                        return response.status, {"message": _compact_error_message(error)}
                    raise TwitchAPIError.response_decode_failed(_compact_error_message(error)) from error
                if not isinstance(payload, dict):
                    raise TwitchAPIError.unexpected_response()
                return response.status, {str(key): value for key, value in payload.items()}
        except TwitchAPIError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as error:
            raise TwitchAPIError.request_failed(_compact_error_message(error)) from error

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise TwitchAPISessionError
        return self._session


def _normalize_access_token(access_token: str) -> str:
    """Normalize access tokens pasted from sources like Chatterino."""
    normalized = access_token.strip()
    if normalized.lower().startswith("oauth:"):
        normalized = normalized[6:]
    return normalized


def _compact_error_message(error: BaseException) -> str:
    return " ".join(str(error).split())
