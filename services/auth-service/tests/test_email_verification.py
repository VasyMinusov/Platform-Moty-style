"""
Тесты email verification: request → confirm.
"""

import pytest
from httpx import AsyncClient

VALID_PASSWORD = "correct horse battery staple nist"


@pytest.fixture
async def registered_headers(client: AsyncClient) -> dict[str, str]:
    """
    Регистрирует пользователя, логинит и возвращает headers.

    Регистрация сразу не отправляет письмо (в текущей реализации),
    поэтому email остаётся неподтверждённым.
    """
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "verify@example.com",
            "username": "verifyme",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "verify@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ═══════════════════════════════════════════════════════════════════════════
# Request
# ═══════════════════════════════════════════════════════════════════════════


async def test_request_verification_email(
    client: AsyncClient,
    registered_headers: dict[str, str],
    email_sender,
) -> None:
    """POST /auth/verify-email → письмо отправлено, mock собрал."""
    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    assert r.status_code == 200, r.text
    assert len(email_sender.sent) == 1
    assert email_sender.sent[0]["to"] == "verify@example.com"
    assert "Подтверждение email" in email_sender.sent[0]["subject"]
    url = email_sender.last_url()
    assert "verify-email" in url
    assert "token=" in url


async def test_request_verification_twice_replaces_token(
    client: AsyncClient,
    registered_headers: dict[str, str],
    email_sender,
) -> None:
    """Повторный запрос инвалидирует предыдущий токен."""
    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    first_token = email_sender.last_token()

    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    second_token = email_sender.last_token()

    assert first_token != second_token

    # Первый токен больше не работает.
    r = await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": first_token},
    )
    assert r.status_code == 400


async def test_request_verification_requires_auth(client: AsyncClient) -> None:
    """Без access-токена → 401."""
    r = await client.post("/api/v1/auth/verify-email")
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Confirm
# ═══════════════════════════════════════════════════════════════════════════


async def test_confirm_email_verification(
    client: AsyncClient,
    registered_headers: dict[str, str],
    email_sender,
) -> None:
    """POST /auth/verify-email/confirm → email подтверждён."""
    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    token = email_sender.last_token()

    r = await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": token},
    )
    assert r.status_code == 200, r.text

    # /users/me показывает is_email_verified=True
    r = await client.get("/api/v1/users/me", headers=registered_headers)
    assert r.json()["is_email_verified"] is True


async def test_confirm_email_verification_token_single_use(
    client: AsyncClient,
    registered_headers: dict[str, str],
    email_sender,
) -> None:
    """Одноразовость: второй confirm с тем же токеном → 400."""
    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    token = email_sender.last_token()

    r = await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": token},
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": token},
    )
    assert r.status_code == 400


async def test_confirm_email_verification_invalid_token(client: AsyncClient) -> None:
    """Невалидный токен → 400."""
    r = await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": "a" * 32},
    )
    assert r.status_code == 400
    assert r.json()["type"].endswith("/invalid-email-token")


async def test_verify_email_already_verified(
    client: AsyncClient,
    registered_headers: dict[str, str],
    email_sender,
) -> None:
    """Повторный запрос письма после подтверждения → 409."""
    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    token = email_sender.last_token()

    await client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": token},
    )

    r = await client.post("/api/v1/auth/verify-email", headers=registered_headers)
    assert r.status_code == 409
    assert r.json()["type"].endswith("/resource-conflict")