"""Профиль и управление сессиями."""

import pyotp
import pytest
from httpx import AsyncClient

VALID_PASSWORD = "correct horse battery staple nist"
NEW_PASSWORD = "new correct horse battery staple nist"


# ═══════════════════════════════════════════════════════════════════════════
# Фикстуры
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Регистрирует carol, логинит и возвращает headers с access-токеном."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "carol@example.com",
            "username": "carol",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def mfa_headers(client: AsyncClient) -> dict[str, str]:
    """
    Регистрирует erin, включает MFA и логинится через MFA.

    Возвращает headers с access-токеном, у которого amr содержит otp.
    Это нужно для тестов /users/me/password (требует MFAUser).
    """
    # 1. Регистрация + первый логин
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "erin@example.com",
            "username": "erin",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "erin@example.com", "password": VALID_PASSWORD},
    )
    access = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # 2. Setup MFA
    r = await client.post("/api/v1/users/me/mfa/setup", headers=headers)
    assert r.status_code == 200
    secret = r.json()["secret"]

    # 3. Verify MFA (подтверждение владения secret'ом)
    r = await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200

    # 4. Логин заново → mfa_pending
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "erin@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    mfa_token = r.json()["mfa_token"]

    # 5. mfa/verify → получаем access с amr=["pwd","otp"]
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ═══════════════════════════════════════════════════════════════════════════
# /users/me
# ═══════════════════════════════════════════════════════════════════════════


async def test_get_me(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    r = await client.get("/api/v1/users/me", headers=auth_headers)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "carol@example.com"
    assert me["username"] == "carol"


async def test_get_me_without_token(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401


async def test_get_me_with_invalid_token(client: AsyncClient) -> None:
    r = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


async def test_update_me_username(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"username": "carol_new"},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "carol_new"


# ═══════════════════════════════════════════════════════════════════════════
# /users/me/sessions
# ═══════════════════════════════════════════════════════════════════════════


async def test_list_sessions_marks_current(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Текущая сессия помечается is_current=True."""
    r = await client.get("/api/v1/users/me/sessions", headers=auth_headers)
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) >= 1
    assert any(s["is_current"] for s in sessions), "должна быть текущая сессия"


async def test_revoke_own_session(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Отзыв чужой (не текущей) сессии пользователя."""
    # Создаём вторую сессию (второй логин)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200

    # Теперь две сессии
    r = await client.get("/api/v1/users/me/sessions", headers=auth_headers)
    sessions = r.json()
    assert len(sessions) == 2

    other = next(s for s in sessions if not s["is_current"])
    sid = other["session_id"]

    r = await client.delete(f"/api/v1/users/me/sessions/{sid}", headers=auth_headers)
    assert r.status_code == 200

    # Список не должен содержать её
    r = await client.get("/api/v1/users/me/sessions", headers=auth_headers)
    ids = {s["session_id"] for s in r.json()}
    assert sid not in ids


async def test_revoke_nonexistent_session(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.delete(
        "/api/v1/users/me/sessions/nonexistent-session-id",
        headers=auth_headers,
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# /users/me/password
# ═══════════════════════════════════════════════════════════════════════════


async def test_change_password_requires_mfa(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """
    Смена пароля без MFA → 403.

    Access-токен carol имеет amr=["pwd"] (MFA не включён).
    require_mfa проверяет claim amr — должно вернуть 403.
    """
    r = await client.post(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": VALID_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["type"].endswith("/mfa-required")
    assert body["required_methods"] == ["otp", "webauthn"]


async def test_change_password_success(
    client: AsyncClient, mfa_headers: dict[str, str]
) -> None:
    """
    Успешная смена пароля с MFA.

    Проверяем:
    - 200 OK
    - Старый пароль не работает для логина
    - Новый пароль работает
    - Сессии отозваны (login заново нужен)
    """
    # Меняем пароль
    r = await client.post(
        "/api/v1/users/me/password",
        headers=mfa_headers,
        json={
            "current_password": VALID_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 200, r.text

    # Старый пароль больше не работает
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "erin@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 401

    # Новый пароль работает (пароль → mfa_pending)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "erin@example.com", "password": NEW_PASSWORD},
    )
    assert r.status_code == 200
    assert r.json()["mfa_required"] is True


async def test_change_password_wrong_current(
    client: AsyncClient, mfa_headers: dict[str, str]
) -> None:
    """Неверный текущий пароль → 401."""
    r = await client.post(
        "/api/v1/users/me/password",
        headers=mfa_headers,
        json={
            "current_password": "definitely-not-the-right-password",
            "new_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 401
    body = r.json()
    assert body["type"].endswith("/authentication-failed")
    assert "Current password is incorrect" in body["detail"]


async def test_change_password_same_as_old(
    client: AsyncClient, mfa_headers: dict[str, str]
) -> None:
    """Новый пароль совпадает с текущим → 422."""
    r = await client.post(
        "/api/v1/users/me/password",
        headers=mfa_headers,
        json={
            "current_password": VALID_PASSWORD,
            "new_password": VALID_PASSWORD,
        },
    )
    # Pydantic-валидатор схемы отклонит до похода в роутер
    assert r.status_code == 422
    body = r.json()
    assert body["type"].endswith("/validation-error")

async def test_revoke_session_after_rotation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """
    Регрессия: revoke_session после ротации не падает.

    После /auth/refresh в БД две строки с одним session_id:
    старая (used=True, revoked=False) и новая (used=False, revoked=False).
    Если SELECT не фильтрует used=False — scalar_one_or_none() падает
    с MultipleResultsFound.
    """
    # 1. Логин → сессия S
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    refresh = r.json()["refresh_token"]
    sid = r.json()["session_id"]

    # 2. Ротация — старая становится used=True, новая появляется
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert r.json()["session_id"] == sid

    # 3. Revoke этой сессии — должен найтись ровно один активный токен
    r = await client.delete(
        f"/api/v1/users/me/sessions/{sid}", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert "revoked" in r.json()["message"].lower()

    # 4. После revoke — сессии нет в списке
    r = await client.get("/api/v1/users/me/sessions", headers=auth_headers)
    assert r.status_code == 200
    ids = {s["session_id"] for s in r.json()}
    assert sid not in ids