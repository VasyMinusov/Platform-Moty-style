"""
Тесты админ-эндпоинтов (/admin/*).

Покрытие:
- Доступ: non-admin → 404, admin без MFA → 403.
- GET /admin/users/{id}: успех + 404.
- POST /admin/users/{id}/unlock: пользователь разблокирован.
- POST /admin/users/{id}/revoke-sessions: все refresh отозваны.
- GET /admin/users/{id}/audit: пагинация.
- promote_user: успех + unknown email.
"""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserStatus
from app.scripts.promote_admin import promote_user

VALID_PASSWORD = "correct horse battery staple nist"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _promote_to_admin(db_session: AsyncSession, email: str) -> None:
    """Повысить пользователя до админа напрямую в БД (через CLI-функцию)."""
    success, message = await promote_user(db_session, email, demote=False)
    assert success, message


async def _register_and_login(
    client: AsyncClient, email: str, username: str
) -> dict:
    """Регистрация + логин. Возвращает токены."""
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": VALID_PASSWORD},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _setup_mfa(client: AsyncClient, access_token: str) -> str:
    """Setup + verify MFA. Возвращает plaintext secret."""
    headers = {"Authorization": f"Bearer {access_token}"}
    r = await client.post("/api/v1/users/me/mfa/setup", headers=headers)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text
    return secret


async def _mfa_login(client: AsyncClient, email: str, secret: str) -> dict:
    """Login → mfa_pending → mfa_verify. Возвращает токены."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert r.status_code == 200, r.text
    mfa_token = r.json()["mfa_token"]
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# Фикстуры
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def regular_user_headers(client: AsyncClient) -> dict[str, str]:
    """Обычный пользователь (не админ), залогинен по паролю."""
    tokens = await _register_and_login(client, "user@example.com", "regular")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
async def admin_without_mfa_headers(
    client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Админ, но залогинен без MFA (amr=["pwd"])."""
    tokens = await _register_and_login(client, "admin-nomfa@example.com", "admin1")
    await _promote_to_admin(db_session, "admin-nomfa@example.com")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
async def admin_headers(
    client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """
    Полноценный админ: MFA setup + verify + promote → login через MFA.

    Итоговый access-токен: amr=["pwd","otp"], is_admin=True в БД.
    """
    # 1. Регистрация + первичный логин (для setup MFA)
    tokens = await _register_and_login(client, "admin@example.com", "admin")
    access = tokens["access_token"]

    # 2. MFA setup + verify
    secret = await _setup_mfa(client, access)

    # 3. Promote через CLI-функцию (пишет в БД, SAVEPOINT)
    await _promote_to_admin(db_session, "admin@example.com")

    # 4. Свежий логин: password → mfa_pending → mfa_verify.
    # Это даст access с amr=["pwd","otp"] и is_admin=True в БД.
    tokens = await _mfa_login(client, "admin@example.com", secret)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ═══════════════════════════════════════════════════════════════════════════
# Доступ
# ═══════════════════════════════════════════════════════════════════════════


async def test_non_admin_gets_404(
    client: AsyncClient, regular_user_headers: dict[str, str]
) -> None:
    """
    Обычный пользователь на /admin/* → 404 (не 403).

    Anti-enumeration: не раскрываем существование admin-эндпоинтов.
    """
    r = await client.get("/api/v1/admin/users/1", headers=regular_user_headers)
    assert r.status_code == 404
    body = r.json()
    assert body["type"].endswith("/resource-not-found")


async def test_admin_without_mfa_gets_403(
    client: AsyncClient, admin_without_mfa_headers: dict[str, str]
) -> None:
    """
    Админ без MFA → 403 mfa-required.

    require_admin строится поверх MFAUser, а require_mfa проверяет
    amr=["otp"/"webauthn"] в текущем access-токене.
    """
    r = await client.get(
        "/api/v1/admin/users/1", headers=admin_without_mfa_headers
    )
    assert r.status_code == 403
    body = r.json()
    assert body["type"].endswith("/mfa-required")


# ═══════════════════════════════════════════════════════════════════════════
# GET /admin/users/{id}
# ═══════════════════════════════════════════════════════════════════════════


async def test_admin_can_get_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
    regular_user_headers: dict[str, str],
) -> None:
    """Админ получает профиль произвольного пользователя."""
    r = await client.get("/api/v1/users/me", headers=regular_user_headers)
    assert r.status_code == 200
    user_id = r.json()["id"]

    r = await client.get(f"/api/v1/admin/users/{user_id}", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == user_id
    assert body["email"] == "user@example.com"
    assert body["is_admin"] is False


async def test_admin_get_nonexistent_user_returns_404(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Несуществующий user_id → 404."""
    r = await client.get("/api/v1/admin/users/999999", headers=admin_headers)
    assert r.status_code == 404
    assert "User" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# POST /admin/users/{id}/unlock
# ═══════════════════════════════════════════════════════════════════════════


async def test_admin_unlock_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    regular_user_headers: dict[str, str],
) -> None:
    """Админ разблокирует пользователя → тот может логиниться."""
    r = await client.get("/api/v1/users/me", headers=regular_user_headers)
    user_id = r.json()["id"]

    # Вручную блокируем в БД
    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.status = UserStatus.LOCKED
    user.locked_until = datetime.now(UTC) + timedelta(hours=1)
    user.failed_attempts = 99
    await db_session.flush()

    # Unlock через админа
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/unlock", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert "unlocked" in r.json()["message"].lower()

    # Проверяем, что пользователь разблокирован
    await db_session.refresh(user)
    assert user.locked_until is None
    assert user.failed_attempts == 0
    assert user.status == UserStatus.ACTIVE


# ═══════════════════════════════════════════════════════════════════════════
# POST /admin/users/{id}/revoke-sessions
# ═══════════════════════════════════════════════════════════════════════════


async def test_admin_revoke_user_sessions(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Админ отзывает все сессии пользователя."""
    # Создать victim с двумя сессиями
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "victim@example.com",
            "username": "victim",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201
    user_id = r.json()["id"]

    r1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": VALID_PASSWORD},
    )
    refresh1 = r1.json()["refresh_token"]

    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": VALID_PASSWORD},
    )
    refresh2 = r2.json()["refresh_token"]

    # Revoke через админа
    r = await client.post(
        f"/api/v1/admin/users/{user_id}/revoke-sessions", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert "Revoked 2" in r.json()["message"]

    # Оба refresh-токена не работают
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh1})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh2})
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# GET /admin/users/{id}/audit
# ═══════════════════════════════════════════════════════════════════════════


async def test_admin_audit_pagination(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Пагинация: limit=2 → 2 items, total >= 3."""
    # Создать victim с историей
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "audit-victim@example.com",
            "username": "auditvictim",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201
    user_id = r.json()["id"]

    # Несколько действий для наполнения audit
    await client.post(
        "/api/v1/auth/login",
        json={"email": "audit-victim@example.com", "password": VALID_PASSWORD},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "audit-victim@example.com", "password": "wrong-password"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "audit-victim@example.com", "password": VALID_PASSWORD},
    )

    # Первая страница: limit=2
    r = await client.get(
        f"/api/v1/admin/users/{user_id}/audit?limit=2&offset=0",
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert body["per_page"] == 2
    assert body["page"] == 1

    # Вторая страница
    r = await client.get(
        f"/api/v1/admin/users/{user_id}/audit?limit=2&offset=2",
        headers=admin_headers,
    )
    assert r.status_code == 200
    body2 = r.json()
    assert body2["page"] == 2
    # id-шники на страницах не пересекаются (сортировка DESC по created_at)
    ids_p1 = {item["id"] for item in body["items"]}
    ids_p2 = {item["id"] for item in body2["items"]}
    assert ids_p1.isdisjoint(ids_p2)


# ═══════════════════════════════════════════════════════════════════════════
# promote_admin script
# ═══════════════════════════════════════════════════════════════════════════


async def test_promote_admin_script(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """promote_user выставляет is_admin=True."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "promote@example.com",
            "username": "promoteme",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    success, _ = await promote_user(db_session, "promote@example.com", demote=False)
    assert success

    result = await db_session.execute(
        select(User).where(User.email == "promote@example.com")
    )
    user = result.scalar_one()
    assert user.is_admin is True


async def test_promote_admin_script_unknown_email(
    db_session: AsyncSession,
) -> None:
    """Несуществующий email → (False, message)."""
    success, message = await promote_user(
        db_session, "nonexistent@example.com", demote=False
    )
    assert success is False
    assert "not found" in message.lower()


async def test_demote_admin_script(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """--demote снимает права."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "demote@example.com",
            "username": "demoteme",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    success, _ = await promote_user(db_session, "demote@example.com", demote=False)
    assert success

    success, message = await promote_user(
        db_session, "demote@example.com", demote=True
    )
    assert success
    assert "demoted" in message.lower()

    result = await db_session.execute(
        select(User).where(User.email == "demote@example.com")
    )
    user = result.scalar_one()
    assert user.is_admin is False