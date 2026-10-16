"""
Утилиты для одноразовых action-токенов (email verification, password reset).

Токен — это 32 байта энтропии в hex. Он попадает в письмо (URL) и НЕ
хранится в БД в открытом виде: сохраняется только HMAC-SHA256-хеш.
"""

import hashlib
import hmac
import secrets
from urllib.parse import urlencode

from app.config import get_settings

# 32 байта = 64 hex-символа. Перебор при 1e9 попыток/сек — ~1.8e19 лет.
ACTION_TOKEN_BYTES: int = 32


def generate_action_token() -> str:
    """Сгенерировать криптостойкий одноразовый токен (hex, 64 символа)."""
    return secrets.token_hex(ACTION_TOKEN_BYTES)


def hash_action_token(raw_token: str) -> str:
    """
    HMAC-SHA256 с серверным секретом.

    HMAC (а не голый SHA-256) — защита от rainbow tables при утечке БД.
    Тот же ключ, что у JWT (jwt_secret_key) — отдельный секрет не нужен.
    """
    secret = get_settings().jwt_secret_key.encode()
    return hmac.new(secret, raw_token.encode(), hashlib.sha256).hexdigest()


def build_frontend_url(path: str, token: str) -> str:
    """
    Собрать URL для письма: `{frontend_url}{path}?token={token}`.

    `path` может быть без ведущего слэша — нормализуем.
    Токен urlencode'ится (hex → безопасно, но инвариант сохраняем).
    """
    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}?{urlencode({'token': token})}"
