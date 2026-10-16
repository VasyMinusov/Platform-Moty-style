"""
Яндекс ID — OAuth2-провайдер.

Документация:
- https://yandex.ru/dev/id/doc/ru/
- Authorize:  GET  https://oauth.yandex.ru/authorize
- Token:      POST https://oauth.yandex.ru/token
- Userinfo:   GET  https://login.yandex.ru/info?format=json

Yandex не поддерживает refresh_token в OAuth2-флоу (выдаёт долгоживущий
access_token ~1 год). Нам это и не нужно: мы не работаем от имени
пользователя в Яндексе — только однократно забираем профиль.
"""

from typing import Any, Final

import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.security.oauth.base import (
    OAuthProviderError,
    OAuthTokens,
    OAuthUserInfo,
)

log = get_logger(__name__)


class YandexProvider:
    """OAuth2-клиент Яндекс ID."""

    slug: Final[str] = "yandex"
    display_name: Final[str] = "Яндекс ID"

    AUTHORIZE_URL: Final[str] = "https://oauth.yandex.ru/authorize"
    TOKEN_URL: Final[str] = "https://oauth.yandex.ru/token"
    USERINFO_URL: Final[str] = "https://login.yandex.ru/info"

    # Таймаут на HTTP-запросы к Яндексу. 10 секунд — компромисс между
    # устойчивостью к сетевым задержкам и временем удержания запроса.
    HTTP_TIMEOUT: Final[float] = 10.0

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.oauth_yandex_client_id
        self._client_secret = settings.oauth_yandex_client_secret

    @property
    def is_configured(self) -> bool:
        """True, если заданы client_id и client_secret."""
        return bool(self._client_id and self._client_secret)

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """
        URL, на который редиректим пользователя.

        `state` — наш подписанный JWT (CSRF-защита). Яндекс вернёт его
        без изменений в callback.
        """
        if not self.is_configured:
            raise OAuthProviderError("provider_not_configured")

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            # "login:email login:info" — минимально необходимые scopes.
            # Яндекс не требует явного scope в authorize — они заданы
            # в настройках приложения в консоли. Оставляем явно для
            # документации.
            "scope": "login:email login:info",
        }
        # httpx.URL корректно кодирует query (в т.ч. наш state).
        return str(httpx.URL(self.AUTHORIZE_URL, params=params))

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
    ) -> OAuthTokens:
        """POST /token → access_token."""
        if not self.is_configured:
            raise OAuthProviderError("provider_not_configured")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
        }

        try:
            async with httpx.AsyncClient(timeout=self.HTTP_TIMEOUT) as client:
                response = await client.post(
                    self.TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError as exc:
            log.error("yandex_token_request_failed", error=str(exc))
            raise OAuthProviderError("provider_unavailable") from exc

        if response.status_code != 200:
            # Не логируем response.text целиком: может содержать PII/токены.
            log.warning(
                "yandex_token_exchange_failed",
                status=response.status_code,
            )
            raise OAuthProviderError(
                "token_exchange_failed",
                description=f"HTTP {response.status_code}",
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            log.error("yandex_token_invalid_json")
            raise OAuthProviderError("token_exchange_failed") from exc

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            log.error("yandex_token_missing_access_token")
            raise OAuthProviderError("token_exchange_failed")

        expires_in_raw = payload.get("expires_in")
        expires_in: int | None = None
        if isinstance(expires_in_raw, int):
            expires_in = expires_in_raw

        return OAuthTokens(
            access_token=access_token,
            token_type=str(payload.get("token_type", "Bearer")),
            expires_in=expires_in,
        )

    async def fetch_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        """GET /info?format=json → профиль."""
        try:
            async with httpx.AsyncClient(timeout=self.HTTP_TIMEOUT) as client:
                response = await client.get(
                    self.USERINFO_URL,
                    params={"format": "json"},
                    headers={"Authorization": f"OAuth {tokens.access_token}"},
                )
        except httpx.HTTPError as exc:
            log.error("yandex_userinfo_request_failed", error=str(exc))
            raise OAuthProviderError("provider_unavailable") from exc

        if response.status_code != 200:
            log.warning(
                "yandex_userinfo_failed",
                status=response.status_code,
            )
            raise OAuthProviderError(
                "userinfo_failed",
                description=f"HTTP {response.status_code}",
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            log.error("yandex_userinfo_invalid_json")
            raise OAuthProviderError("userinfo_failed") from exc

        provider_user_id = payload.get("id")
        if not isinstance(provider_user_id, str) or not provider_user_id:
            log.error("yandex_userinfo_missing_id")
            raise OAuthProviderError("userinfo_failed")

        # Email: сначала default_email (подтверждённый Яндексом), потом
        # первый из emails[].
        email = payload.get("default_email")
        if not isinstance(email, str) or not email:
            emails = payload.get("emails")
            if isinstance(emails, list) and emails and isinstance(emails[0], str):
                email = emails[0]
            else:
                email = None

        # Яндекс подтверждает email своим процессом регистрации —
        # считаем email верифицированным, если он вообще есть.
        # (У Яндекса нет поля "verified" в userinfo; email по определению
        # его собственный.)
        email_verified = email is not None

        username = payload.get("login")
        if not isinstance(username, str):
            username = None

        full_name = payload.get("real_name") or payload.get("display_name")
        if not isinstance(full_name, str):
            full_name = None

        return OAuthUserInfo(
            provider_user_id=provider_user_id,
            email=email,
            email_verified=email_verified,
            username=username,
            full_name=full_name,
        )
