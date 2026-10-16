"""
Работа с refresh-сессиями: создание, persist.

Вынесено из `app/routers/auth.py` для переиспользования в OAuth-роутере
без приватных импортов `_persist_refresh_token`.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import RefreshToken


def hash_token(token: str) -> str:
    """
    HMAC-SHA256 refresh-токена с серверным секретом.

    NIST: не храним сам токен, только хеш. HMAC защищает от rainbow tables
    при утечке БД.
    """
    secret = get_settings().jwt_secret_key.encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()


async def persist_refresh_token(
    db: AsyncSession,
    *,
    user_id: int,
    tokens: dict[str, Any],
    client: dict[str, str | None],
) -> None:
    """
    Сохранить refresh-токен в БД для revocation.

    НЕ коммитит — ответственность вызывающего (get_db сделает commit).
    НЕ инкрементит `auth_sessions_created_total` — это ответственность
    вызывающего кода: refresh (ротация) не создаёт новую сессию.
    """
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user_id,
            jti=tokens["refresh_jti"],
            session_id=tokens["session_id"],
            token_hash=hash_token(tokens["refresh_token"]),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.jwt_refresh_token_expire_days),
            ip_address=client.get("ip_address"),
            user_agent=client.get("user_agent"),
        )
    )
