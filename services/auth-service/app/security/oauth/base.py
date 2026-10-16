"""
Контракт OAuth-провайдера + общие dataclass'ы.

Protocol (не ABC): реализации могут быть где угодно, контракт
структурный. Тестам удобно подсовывать MockProvider без наследования.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class OAuthUserInfo:
    """
    Унифицированный профиль от провайдера.

    Все поля, кроме provider_user_id, — опциональные: разные провайдеры
    возвращают разный набор. `provider_user_id` обязателен — это ключ
    для поиска существующей привязки.
    """

    provider_user_id: str
    email: str | None
    email_verified: bool
    username: str | None = None
    full_name: str | None = None


@dataclass(frozen=True)
class OAuthTokens:
    """
    Токены от провайдера (НЕ наши JWT).

    Хранятся только в памяти на время одного callback'а. В БД не пишутся
    (см. models.OAuthAccount).
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None


class OAuthProviderError(Exception):
    """
    Ошибка от провайдера или при обмене.

    `reason` — машиночитаемый код (`token_exchange_failed`,
    `userinfo_failed`, `provider_unavailable`). Роутер конвертирует
    в редирект на frontend: `{frontend_url}#error={reason}`.

    Не ProblemError (RFC 9457): callback не возвращает 4xx/5xx,
    он всегда редиректит.
    """

    def __init__(self, reason: str, description: str | None = None) -> None:
        self.reason = reason
        self.description = description
        super().__init__(reason)


@runtime_checkable
class OAuthProvider(Protocol):
    """
    Контракт OAuth2-провайдера.

    Реализация должна быть безопасна для параллельных вызовов
    (async, без общего mutable state).

    Атрибуты объявлены через @property (read-only): реализация может
    использовать либо `@property`, либо class-level `Final` — оба
    варианта структурно совместимы. Обычная settable-переменная в
    Protocol'е требовала бы, чтобы реализация тоже была settable,
    что для `Final`-констант неверно.
    """

    @property
    def slug(self) -> str:
        """Публичный slug для URL: `/auth/oauth/{slug}/authorize`."""
        ...

    @property
    def display_name(self) -> str:
        """Человекочитаемое имя для UI: "Яндекс ID"."""
        ...

    @property
    def is_configured(self) -> bool:
        """
        True, если провайдер сконфигурирован (client_id + secret заданы).

        Не путать с oauth_enabled — тот глобальный feature flag.
        """
        ...

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Собрать URL, на который редиректим пользователя."""
        ...

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
    ) -> OAuthTokens:
        """
        Обменять authorization code на access-токен провайдера.

        Бросает OAuthProviderError при любой ошибке (сеть, 4xx/5xx от
        провайдера, невалидный JSON).
        """
        ...

    async def fetch_user_info(self, tokens: OAuthTokens) -> OAuthUserInfo:
        """
        Получить профиль пользователя.

        Бросает OAuthProviderError при любой ошибке.
        """
        ...
