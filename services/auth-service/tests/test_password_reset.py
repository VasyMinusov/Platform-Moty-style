"""
Тесты password reset: request → confirm.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    clear_reset_interval_quota,
    reset_and_reinit_rate_limiter,
)

VALID_PASSWORD = "correct horse battery staple nist"
NEW_PASSWORD = "totally different password 42!"


@pytest.fixture
async def registered_user(client: AsyncClient) -> dict:
    """Регистрирует пользователя и возвращает его данные."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "reset@example.com",
            "username": "resetme",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# Request
# ═══════════════════════════════════════════════════════════════════════════


async def test_request_reset_for_existing_email(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """Для существующего email → письмо отправлено, generic 200."""
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    assert "If the provided email" in r.json()["message"]
    assert len(email_sender.sent) == 1
    assert email_sender.sent[0]["to"] == "reset@example.com"


async def test_request_reset_for_unknown_email(
    client: AsyncClient,
    email_sender,
) -> None:
    """Для несуществующего email → тот же generic 200, письма нет."""
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "nobody@example.com"},
    )
    assert r.status_code == 200
    assert "If the provided email" in r.json()["message"]
    assert len(email_sender.sent) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Confirm
# ═══════════════════════════════════════════════════════════════════════════


async def test_full_password_reset_flow(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """Полный flow: request → confirm → старый пароль не работает, новый работает."""
    # 1. Request
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    token = email_sender.last_token()

    # 2. Confirm
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200, r.text

    # 3. Старый пароль не работает
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 401

    # 4. Новый пароль работает
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": NEW_PASSWORD},
    )
    assert r.status_code == 200


async def test_reset_revokes_active_sessions(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """После сброса пароля все активные сессии отозваны."""
    # Логин (создаёт сессию)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": VALID_PASSWORD},
    )
    old_refresh = r.json()["refresh_token"]

    # Reset
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    token = email_sender.last_token()

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200

    # Старый refresh больше не работает
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert r.status_code == 401


async def test_reset_token_single_use(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """Повторное использование токена → 400."""
    await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    token = email_sender.last_token()

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400


async def test_reset_new_password_policy_violation(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """Слишком короткий новый пароль → 422."""
    await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    token = email_sender.last_token()

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "short"},
    )
    assert r.status_code == 422
    assert r.json()["type"].endswith("/password-policy")


async def test_reset_invalid_token(client: AsyncClient) -> None:
    """Невалидный токен → 400."""
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "x" * 32, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400


async def test_reset_request_invalidates_old_token(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """
    Новый request инвалидирует предыдущий токен.

    Min-interval (60 сек) в prod-коде намеренно throttle'ит второй запрос —
    в тесте сбрасываем только этот scope (hourly-quota не трогаем),
    чтобы проверить именно инвалидацию токена.
    """
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    first_token = email_sender.last_token()

    # Обходим min-interval, но не hourly-quota.
    await clear_reset_interval_quota()

    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    second_token = email_sender.last_token()

    assert first_token != second_token

    # Первый токен не работает.
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first_token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 400

    # Второй работает.
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second_token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Rate limit
# ═══════════════════════════════════════════════════════════════════════════


async def test_password_reset_hourly_quota(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """
    4-й request (за час) → 429.

    Между запросами сбрасываем ТОЛЬКО min-interval (scope="reset_interval") —
    hourly-quota (scope="reset") накапливается как в prod.
    """
    for i in range(3):
        # Обходим min-interval, чтобы запросы не блокировались
        # до достижения hourly-лимита.
        await clear_reset_interval_quota()

        r = await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset@example.com"},
        )
        assert r.status_code == 200, f"request {i + 1}: {r.status_code}"

    # 4-й — превышение hourly (reset scope), 429.
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 429, r.text
    assert r.json()["type"].endswith("/rate-limit-exceeded")


async def test_password_reset_min_interval(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """
    Два запроса < min_interval секунд → 200 generic, письмо не отправлено.

    Anti-enumeration: даже если бы email не существовал, ответ был бы 200.
    Пользователь не должен узнать, что throttle'ится.
    """
    # Первый — письмо уходит.
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    assert len(email_sender.sent) == 1

    # Второй сразу — 200, но письма нет.
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    assert "If the provided email" in r.json()["message"]
    # Писем по-прежнему 1.
    assert len(email_sender.sent) == 1


async def test_password_reset_interval_bypassed_with_fresh_limiter(
    client: AsyncClient,
    registered_user: dict,
    email_sender,
) -> None:
    """
    Сброс rate limiter между запросами позволяет обойти min_interval.

    Это подтверждает, что interval — именно rate limiter, а не что-то
    в БД/email-сендере (что сбрасывать было бы нельзя).
    """
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    assert len(email_sender.sent) == 1

    await reset_and_reinit_rate_limiter()

    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert r.status_code == 200
    # Теперь письмо ушло (лимитер сброшен).
    assert len(email_sender.sent) == 2