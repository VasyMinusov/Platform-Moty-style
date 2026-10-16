"""Ошибочные сценарии аутентификации."""

import pytest
from httpx import AsyncClient

VALID_PASSWORD = "correct horse battery staple nist"


@pytest.fixture
async def registered_user(client: AsyncClient) -> dict:
    """Регистрирует пользователя bob и возвращает его данные."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bob@example.com",
            "username": "bob",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# Login
# ═══════════════════════════════════════════════════════════════════════════


async def test_login_wrong_password(client: AsyncClient, registered_user: dict) -> None:
    """Неверный пароль → 401 с generic-сообщением."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "wrong-password-12345"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["type"].endswith("/authentication-failed")
    # Generic message — не раскрываем разницу между «нет юзера» и «неверный пароль»
    assert "Invalid email or password" in body["detail"]


async def test_login_unknown_user(client: AsyncClient) -> None:
    """Неизвестный email → 401 с тем же generic-сообщением."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["type"].endswith("/authentication-failed")
    assert "Invalid email or password" in body["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# Register
# ═══════════════════════════════════════════════════════════════════════════


async def test_register_duplicate_email(client: AsyncClient, registered_user: dict) -> None:
    """Повторная регистрация с тем же email → 409."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bob@example.com",
            "username": "bob2",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 409
    assert r.json()["type"].endswith("/resource-conflict")


async def test_register_weak_password(client: AsyncClient) -> None:
    """Пароль < 15 символов → 422 с password-policy."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "weak@example.com",
            "username": "weak",
            "password": "short",
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["type"].endswith("/password-policy")
    assert any("at least 15" in e for e in body["errors"])


async def test_register_password_contains_username(client: AsyncClient) -> None:
    """Пароль содержит username → 422."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "selfref@example.com",
            "username": "selfref",
            "password": "my-selfref-password-12345",
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["type"].endswith("/password-policy")
    assert any("username" in e for e in body["errors"])


# ═══════════════════════════════════════════════════════════════════════════
# Refresh
# ═══════════════════════════════════════════════════════════════════════════


async def test_refresh_replay_detection(client: AsyncClient, registered_user: dict) -> None:
    """
    Replay detection: повторное использование использованного refresh
    инвалидирует все сессии пользователя.
    """
    # Логин
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    old_refresh = r.json()["refresh_token"]

    # Первый refresh — OK
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]

    # Второй refresh со СТАРЫМ токеном — replay
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401
    assert "replay" in r.json()["detail"].lower()

    # После replay-detect — и новый refresh уже не работает
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r.status_code == 401


async def test_access_token_rejected_as_refresh(
    client: AsyncClient, registered_user: dict
) -> None:
    """Access-токен, предъявленный в /refresh, отклоняется."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": VALID_PASSWORD},
    )
    access = r.json()["access_token"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert r.status_code == 401
    assert "Not a refresh token" in r.json()["detail"]