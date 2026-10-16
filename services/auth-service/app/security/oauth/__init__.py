"""
OAuth2-клиент для внешних identity providers.

Публичный API:
- `OAuthProvider` — Protocol (контракт).
- `OAuthUserInfo`, `OAuthTokens` — dataclass'ы.
- `OAuthProviderError` — исключение для ошибок провайдера.
- `get_provider(slug)` — фабрика провайдеров.

Реализации:
- `YandexProvider` (app/security/oauth/yandex.py).

В защищённом контуре весь модуль не используется:
роутер `app/routers/oauth.py` не монтируется при `oauth_enabled=False`.
"""

from app.security.oauth.base import (
    OAuthProvider,
    OAuthProviderError,
    OAuthTokens,
    OAuthUserInfo,
)
from app.security.oauth.yandex import YandexProvider

__all__ = [
    "OAuthProvider",
    "OAuthProviderError",
    "OAuthTokens",
    "OAuthUserInfo",
    "YandexProvider",
    "get_provider",
    "get_enabled_providers",
]


def get_provider(slug: str) -> OAuthProvider | None:
    """
    Получить реализацию провайдера по slug.

    Возвращает None, если провайдер неизвестен ИЛИ не сконфигурирован
    (пустые client_id/secret). Роутер маппит None → 404.
    """
    if slug == "yandex":
        provider = YandexProvider()
        return provider if provider.is_configured else None
    return None


def get_enabled_providers() -> list[OAuthProvider]:
    """
    Список активных провайдеров (для GET /auth/oauth/providers).

    Сейчас — только Яндекс. При добавлении Google/GitHub — расширить.
    """
    result: list[OAuthProvider] = []
    yandex = YandexProvider()
    if yandex.is_configured:
        result.append(yandex)
    return result
