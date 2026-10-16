"""Тесты Prometheus /metrics endpoint."""

import pyotp
import pytest
from httpx import AsyncClient

VALID_PASSWORD = "correct horse battery staple nist"
NEW_PASSWORD = "totally different password 42!"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_metrics(client: AsyncClient) -> str:
    """Скачать /metrics как plain text."""
    r = await client.get("/metrics")
    assert r.status_code == 200, r.text
    return r.text


def _metric_value(body: str, key: str) -> float:
    """
    Значение метрики по точному ключу (имя + метки).

    Формат строки в Prometheus exposition:
        auth_sessions_created_total 5.0
        auth_sessions_revoked_total{reason="logout"} 3.0

    key должен включать метки в каноническом виде (сортированном),
    например: 'auth_sessions_revoked_total{reason="logout"}'.

    Возвращает 0.0, если метрика ещё не появлялась (Counter не
    экспортируется, пока не было ни одного .inc()). Это удобно для
    проверки «до» — но для проверки «после» нужен явный assert > before.
    """
    prefix = key + " "
    for line in body.splitlines():
        if line.startswith(prefix):
            return float(line[len(prefix):].strip())
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Базовые
# ═══════════════════════════════════════════════════════════════════════════


async def test_metrics_endpoint_returns_200(client: AsyncClient) -> None:
    """/metrics доступен и возвращает text/plain (Prometheus format)."""
    r = await client.get("/metrics")
    assert r.status_code == 200, r.text
    assert "text/plain" in r.headers["content-type"]


async def test_metrics_contains_domain_counters(client: AsyncClient) -> None:
    """/metrics содержит наши доменные метрики."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "metric@example.com",
            "username": "metricuser",
            "password": VALID_PASSWORD,
        },
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "metric@example.com", "password": VALID_PASSWORD},
    )

    body = await _fetch_metrics(client)

    # HTTP-метрики от Instrumentator
    assert "http_requests_total" in body
    # Доменные метрики
    assert "auth_logins_total" in body
    assert "auth_lockouts_total" in body
    assert "auth_mfa_verifications_total" in body
    assert "auth_token_refresh_total" in body
    assert "auth_email_actions_total" in body
    # Сессии (новые Counter'ы)
    assert "auth_sessions_created_total" in body


# ═══════════════════════════════════════════════════════════════════════════
# Login / lockout (существующие)
# ═══════════════════════════════════════════════════════════════════════════


async def test_metrics_login_success_label(client: AsyncClient) -> None:
    """После успешного login auth_logins_total{result="success"} > 0."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "metric2@example.com",
            "username": "metricuser2",
            "password": VALID_PASSWORD,
        },
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "metric2@example.com", "password": VALID_PASSWORD},
    )

    body = await _fetch_metrics(client)
    value = _metric_value(body, 'auth_logins_total{result="success"}')
    assert value >= 1.0


async def test_metrics_login_failure_label(client: AsyncClient) -> None:
    """После неудачного login auth_logins_total{result="invalid_credentials"} > 0."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "metric3@example.com",
            "username": "metricuser3",
            "password": VALID_PASSWORD,
        },
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "metric3@example.com", "password": "wrong-password-attempt"},
    )

    body = await _fetch_metrics(client)
    value = _metric_value(
        body, 'auth_logins_total{result="invalid_credentials"}'
    )
    assert value >= 1.0


async def test_metrics_lockout_label(client: AsyncClient) -> None:
    """После lockout'а auth_lockouts_total{scope="login"} > 0."""
    from app.security.rate_limit import get_rate_limiter

    limiter = get_rate_limiter()
    identifier = "lockout-metric@example.com"

    # Исчерпываем лимит — 10 неудачных попыток.
    for _ in range(10):
        await limiter.record_failure("login", identifier)

    # HTTP-запрос — должен вернуть 423 + инкрементить метрику.
    await client.post(
        "/api/v1/auth/login",
        json={"email": identifier, "password": "any-password-here-1234"},
    )

    body = await _fetch_metrics(client)
    value = _metric_value(body, 'auth_lockouts_total{scope="login"}')
    assert value >= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Sessions: created
# ═══════════════════════════════════════════════════════════════════════════


async def test_session_created_on_login(client: AsyncClient) -> None:
    """Успешный login (без MFA) инкрементит auth_sessions_created_total на 1."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "created1@example.com",
            "username": "createduser1",
            "password": VALID_PASSWORD,
        },
    )

    before = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "created1@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )
    assert after == before + 1.0


async def test_session_created_on_mfa_login(client: AsyncClient) -> None:
    """Успешный MFA-login инкрементит auth_sessions_created_total на 1."""
    # Регистрация + первичный login
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "created2@example.com",
            "username": "createduser2",
            "password": VALID_PASSWORD,
        },
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "created2@example.com", "password": VALID_PASSWORD},
    )
    access = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # Setup + verify MFA
    r = await client.post("/api/v1/users/me/mfa/setup", headers=headers)
    secret = r.json()["secret"]
    await client.post(
        "/api/v1/users/me/mfa/verify",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )

    # Второй login → mfa_pending
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "created2@example.com", "password": VALID_PASSWORD},
    )
    mfa_token = r.json()["mfa_token"]

    before = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )

    # mfa/verify → создаёт сессию
    r = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )
    assert after == before + 1.0


async def test_session_not_created_on_refresh(client: AsyncClient) -> None:
    """
    Ротация refresh НЕ инкрементит auth_sessions_created_total.

    Это ключевое отличие от login: сессия та же, refresh-токен новый.
    Без этого различия created_total рос бы на каждый refresh и не
    коррелировал с числом реальных логинов.
    """
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "created3@example.com",
            "username": "createduser3",
            "password": VALID_PASSWORD,
        },
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "created3@example.com", "password": VALID_PASSWORD},
    )
    refresh_token = r.json()["refresh_token"]

    before = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )

    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client), "auth_sessions_created_total"
    )
    assert after == before  # не изменилось


# ═══════════════════════════════════════════════════════════════════════════
# Sessions: revoked
# ═══════════════════════════════════════════════════════════════════════════


async def test_session_revoked_on_logout(client: AsyncClient) -> None:
    """Logout одной сессии → auth_sessions_revoked_total{reason="logout"} += 1."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke1@example.com",
            "username": "revokeuser1",
            "password": VALID_PASSWORD,
        },
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke1@example.com", "password": VALID_PASSWORD},
    )
    tokens = r.json()

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="logout"}',
    )

    r = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"], "all_sessions": False},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="logout"}',
    )
    assert after == before + 1.0


async def test_session_revoked_on_logout_all(client: AsyncClient) -> None:
    """Logout со всех → auth_sessions_revoked_total{reason="logout_all"} += N."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke2@example.com",
            "username": "revokeuser2",
            "password": VALID_PASSWORD,
        },
    )
    # Две сессии
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke2@example.com", "password": VALID_PASSWORD},
    )
    first = r.json()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke2@example.com", "password": VALID_PASSWORD},
    )
    second = r.json()

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="logout_all"}',
    )

    r = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={"refresh_token": first["refresh_token"], "all_sessions": True},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="logout_all"}',
    )
    # Обе сессии (first + second) отозваны одним UPDATE → +2.
    assert after == before + 2.0

    # Заглушаем предупреждение о неиспользуемом second.
    assert second["session_id"] != first["session_id"]


async def test_session_revoked_on_user_revoke_one(client: AsyncClient) -> None:
    """DELETE /users/me/sessions/{sid} → reason="user_revoked" += 1."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke3@example.com",
            "username": "revokeuser3",
            "password": VALID_PASSWORD,
        },
    )
    # Первая сессия — будет использоваться как «текущая» в запросе.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke3@example.com", "password": VALID_PASSWORD},
    )
    first = r.json()
    # Вторая — её будем отзывать.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke3@example.com", "password": VALID_PASSWORD},
    )
    second = r.json()

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="user_revoked"}',
    )

    r = await client.delete(
        f"/api/v1/users/me/sessions/{second['session_id']}",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="user_revoked"}',
    )
    assert after == before + 1.0


async def test_session_revoked_on_user_revoke_all(client: AsyncClient) -> None:
    """DELETE /users/me/sessions → reason="user_revoked_all" += N."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke4@example.com",
            "username": "revokeuser4",
            "password": VALID_PASSWORD,
        },
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke4@example.com", "password": VALID_PASSWORD},
    )
    first = r.json()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke4@example.com", "password": VALID_PASSWORD},
    )
    _ = r.json()  # вторая сессия, должна быть отозвана

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="user_revoked_all"}',
    )

    r = await client.delete(
        "/api/v1/users/me/sessions",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="user_revoked_all"}',
    )
    assert after == before + 2.0


async def test_session_revoked_on_password_reset(
    client: AsyncClient, email_sender
) -> None:
    """Password reset revoke'ает все сессии → reason="password_reset" += N."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke5@example.com",
            "username": "revokeuser5",
            "password": VALID_PASSWORD,
        },
    )
    # Две активные сессии.
    await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke5@example.com", "password": VALID_PASSWORD},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke5@example.com", "password": VALID_PASSWORD},
    )

    # Запрос сброса → токен в письме.
    r = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "revoke5@example.com"},
    )
    assert r.status_code == 200
    token = email_sender.last_token()

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="password_reset"}',
    )

    # Confirm — revoke всех сессий.
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="password_reset"}',
    )
    assert after == before + 2.0


async def test_session_revoked_on_replay(client: AsyncClient) -> None:
    """Refresh replay → reason="replay_detected" += N (все активные сессии)."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "revoke6@example.com",
            "username": "revokeuser6",
            "password": VALID_PASSWORD,
        },
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "revoke6@example.com", "password": VALID_PASSWORD},
    )
    old_refresh = r.json()["refresh_token"]

    # Первый refresh — OK, старый помечается used, выдаётся новый.
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert r.status_code == 200
    # new_refresh остаётся живым (revoked=False) и должен быть отозван
    # при replay-detect.
    _ = r.json()["refresh_token"]

    before = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="replay_detected"}',
    )

    # Replay старым → revoke всех активных сессий.
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert r.status_code == 401
    assert "replay" in r.json()["detail"].lower()

    after = _metric_value(
        await _fetch_metrics(client),
        'auth_sessions_revoked_total{reason="replay_detected"}',
    )
    # Была одна живая сессия (new_refresh) — её отозвали.
    assert after == before + 1.0