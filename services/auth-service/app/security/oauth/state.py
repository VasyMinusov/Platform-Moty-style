"""
Подписанный state для OAuth-flow.

Зачем: RFC 6749 §10.12 требует `state` для CSRF-защиты. Мы генерим
подписанный JWT с коротким TTL — верифицируем подпись и exp при
callback. Это stateless (не нужен Redis), но защищает от:
- CSRF: атакующий не может подделать state;
- replay: TTL 5 минут;
- cross-provider: state проверяет, что callback пришёл от того же
  провайдера, что инициировал flow.

Не используем `jwt_handler.JWTHandler` — он про access/refresh с
другими claims (`typ`, `amr`, `sid`). Здесь нужен минимальный payload
без лишних полей.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError
from jose import jwt as jose_jwt

from app.config import get_settings


class OAuthStateError(Exception):
    """Невалидный/истёкший/подделанный state."""


def sign_state(*, provider: str) -> str:
    """
    Создать подписанный state-токен.

    Args:
        provider: slug провайдера ("yandex"). Связывает state с
            конкретным провайдером — callback от другого провайдера
            с этим state будет отклонён.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.oauth_state_ttl_seconds)

    payload: dict[str, Any] = {
        "provider": provider,
        # nonce — для аудита/отладки: в логах видно, что state-ы разные,
        # даже если созданы в одну секунду.
        "nonce": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    # HS256 — симметричный, у нас уже есть jwt_secret_key ≥32 символа.
    # Асимметричный тут не нужен: state валидируем сами, не отдаём
    # внешним потребителям.
    token: str = jose_jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return token


def verify_state(state: str, *, expected_provider: str) -> None:
    """
    Проверить state.

    Бросает OAuthStateError, если:
    - подпись неверна / токен истёк / не JWT;
    - provider в payload не совпадает с ожидаемым (защита от
      cross-provider callback).

    Возвращает None при успехе (side-effect-free API — вызывающему
    нужен только факт валидности).
    """
    settings = get_settings()

    try:
        payload: dict[str, Any] = jose_jwt.decode(
            state,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            # Наш state не имеет aud/iss — отключаем встроенную валидацию
            # python-jose 3.5+, иначе JWTClaimsError на отсутствующих claims.
            options={"verify_aud": False, "verify_iss": False},
        )
    except JWTError as exc:
        raise OAuthStateError("invalid_state") from exc

    if payload.get("provider") != expected_provider:
        raise OAuthStateError("provider_mismatch")
