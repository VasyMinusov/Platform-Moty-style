"""
Тесты MFA (TOTP): setup → verify → login с MFA → disable.

Проверяем:
- Полный lifecycle: setup / verify / login / mfa-verify / disable
- Backup-коды: работают и одноразовые
- Защита: нельзя подтвердить setup без кода, нельзя отключить без кода
- Login без MFA не затронут
"""

import json

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MFADevice
from app.security.mfa import decrypt_secret, generate_totp_code

VALID_PASSWORD = "correct horse battery staple nist"


# ═══════════════════════════════════════════════════════════════════════════
# Фикстуры
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Регистрирует dave, логинит, возвращает headers с access-токеном."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "dave@example.com",
            "username": "dave",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def mfa_enabled_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> dict:
    """
    Регистрирует + включает MFA. Возвращает:
        secret       — plaintext TOTP-secret
        backup_codes — список plaintext backup-кодов
        headers      — access-токен
    """
    r = await client.post("/api/v1/users/me/mfa/setup", headers=auth_headers)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]

    r = await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=auth_headers,
        json={"code": generate_totp_code(secret)},
    )
    assert r.status_code == 200, r.text
    backup_codes = r.json()["backup_codes"]

    return {
        "secret": secret,
        "backup_codes": backup_codes,
        "headers": auth_headers,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════


async def test_mfa_setup_returns_secret_and_url(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Setup возвращает plaintext secret и otpauth_url."""
    r = await client.post("/api/v1/users/me/mfa/setup", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["secret"]
    assert body["otpauth_url"].startswith("otpauth://totp/")
    assert body["issuer"]

    # Secret — валидный base32
    assert pyotp.TOTP(body["secret"]).now().isdigit()
    assert len(pyotp.TOTP(body["secret"]).now()) == 6


async def test_mfa_setup_twice_when_already_enabled(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """Повторный setup после подтверждения → 409."""
    r = await client.post(
        "/api/v1/users/me/mfa/setup",
        headers=mfa_enabled_user["headers"],
    )
    assert r.status_code == 409
    assert r.json()["type"].endswith("/resource-conflict")


# ═══════════════════════════════════════════════════════════════════════════
# Verify setup
# ═══════════════════════════════════════════════════════════════════════════


async def test_mfa_verify_setup_wrong_code(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Подтверждение setup с неверным TOTP-кодом → 401."""
    r = await client.post("/api/v1/users/me/mfa/setup", headers=auth_headers)
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=auth_headers,
        json={"code": "000000"},
    )
    assert r.status_code == 401
    assert r.json()["type"].endswith("/authentication-failed")


async def test_mfa_verify_setup_with_valid_code(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Полный flow: setup → verify → backup-коды + is_mfa_enabled=True."""
    r = await client.post("/api/v1/users/me/mfa/setup", headers=auth_headers)
    secret = r.json()["secret"]

    r = await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=auth_headers,
        json={"code": generate_totp_code(secret)},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert len(body["backup_codes"]) == 10
    assert all("-" in c and len(c) == 11 for c in body["backup_codes"])

    # /users/me показывает is_mfa_enabled=True
    r = await client.get("/api/v1/users/me", headers=auth_headers)
    assert r.json()["is_mfa_enabled"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Login с MFA
# ═══════════════════════════════════════════════════════════════════════════


async def test_login_with_mfa_returns_pending_token(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """Login при включённом MFA → mfa_required + mfa_token, без access."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["expires_in"] > 0
    assert "access_token" not in body
    assert "refresh_token" not in body


async def test_full_mfa_login_flow(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """Login → mfa_required → /auth/mfa/verify → access работает."""
    # 1. Login (пароль) → mfa_pending
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    mfa_token = r.json()["mfa_token"]

    # 2. MFA verify с текущим TOTP
    code = generate_totp_code(mfa_enabled_user["secret"])
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    # 3. /users/me с новым access
    r = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "dave@example.com"
    assert r.json()["is_mfa_enabled"] is True


async def test_mfa_login_with_backup_code_is_one_time(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """Backup-код работает один раз, потом — 401."""
    backup = mfa_enabled_user["backup_codes"][0]

    # Login для получения mfa_token
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    # Первый раз — success
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": backup},
    )
    assert r.status_code == 200, r.text

    # Тот же backup — 401
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": backup},
    )
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Disable
# ═══════════════════════════════════════════════════════════════════════════


async def test_mfa_disable_requires_valid_code(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """Disable без кода → 401; с валидным → 200; MFA отключён."""
    headers = mfa_enabled_user["headers"]

    # Неверный код → 401
    r = await client.post(
        "/api/v1/users/me/mfa/disable",
        headers=headers,
        json={"code": "000000"},
    )
    assert r.status_code == 401

    # Валидный TOTP → 200
    code = generate_totp_code(mfa_enabled_user["secret"])
    r = await client.post(
        "/api/v1/users/me/mfa/disable",
        headers=headers,
        json={"code": code},
    )
    assert r.status_code == 200, r.text

    # /users/me показывает is_mfa_enabled=False
    r = await client.get("/api/v1/users/me", headers=headers)
    assert r.json()["is_mfa_enabled"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Дополнительно: проверяем, что MFA-секрет в БД зашифрован
# ═══════════════════════════════════════════════════════════════════════════


async def test_mfa_secret_is_encrypted_in_db(
    client: AsyncClient, mfa_enabled_user: dict, db_session: AsyncSession
) -> None:
    """В БД лежит шифртекст, не plaintext secret."""
    secret_plain = mfa_enabled_user["secret"]

    result = await db_session.execute(select(MFADevice))
    device = result.scalar_one()
    assert device.secret_encrypted != secret_plain
    # Проверяем, что это JSON от EncryptedPayload
    payload = json.loads(device.secret_encrypted)
    assert "profile" in payload
    assert "ciphertext" in payload


# ═══════════════════════════════════════════════════════════════════════════
# Replay protection
# ═══════════════════════════════════════════════════════════════════════════


async def test_totp_code_replay_rejected(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """
    NIST SP 800-63B Rev 4 §5.1.2: OTP SHALL NOT быть принят дважды.

    Тот же TOTP-код нельзя использовать для второго login в пределах
    его окна валидности (обычно 30-90 секунд).
    """
    secret = mfa_enabled_user["secret"]
    code = generate_totp_code(secret)

    # Первый login — success
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert r.status_code == 200, r.text

    # Второй login с тем же кодом — 401 (replay detected)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert r.status_code == 401
    assert r.json()["type"].endswith("/authentication-failed")


async def test_totp_step_stored_after_verify(
    client: AsyncClient, mfa_enabled_user: dict, db_session: AsyncSession
) -> None:
    """После успешного MFA login last_used_totp_step обновляется."""
    # Первый login+verify
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    code = generate_totp_code(mfa_enabled_user["secret"])
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert r.status_code == 200

    # В БД step сохранён
    result = await db_session.execute(select(MFADevice))
    device = result.scalar_one()
    assert device.last_used_totp_step is not None
    assert device.last_used_totp_step > 0

# ═══════════════════════════════════════════════════════════════════════════
# Rate limit
# ═══════════════════════════════════════════════════════════════════════════


async def test_mfa_verify_lockout_after_failures(
    client: AsyncClient, mfa_enabled_user: dict
) -> None:
    """
    NIST §5.2.2: rate limiting на failed MFA attempts.

    После rate_limit_mfa_verify_max_attempts (5) неверных кодов —
    423 Locked. При этом сам TOTP-код не подбирается brute-force
    (10^6 комбинаций, 5 попыток за 15 минут — бесполезно).
    """
    for i in range(5):
        # Login → mfa_pending
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "dave@example.com", "password": VALID_PASSWORD},
        )
        assert r.status_code == 200
        mfa_token = r.json()["mfa_token"]

        # Неверный код
        r = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": mfa_token, "code": "000000"},
        )
        assert r.status_code == 401, f"попытка {i + 1}: {r.status_code}"

    # 6-й login → mfa/verify → 423
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200
    mfa_token = r.json()["mfa_token"]

    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": generate_totp_code(mfa_enabled_user["secret"])},
    )
    # Даже с правильным кодом — 423, потому что scope="mfa" заблокирован.
    assert r.status_code == 423
    body = r.json()
    assert body["type"].endswith("/account-locked")
    assert "retry_after" in body