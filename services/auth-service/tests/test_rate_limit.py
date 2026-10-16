"""
Тесты rate limiter: lockout (login/mfa) + quota (verify/reset).
"""

import pytest

from app.security.rate_limit import (
    InMemoryRateLimiter,
    _compute_lockout_seconds,
    get_rate_limiter,
)


# ═══════════════════════════════════════════════════════════════════════════
# Lockout: базовые сценарии
# ═══════════════════════════════════════════════════════════════════════════


async def test_not_locked_initially() -> None:
    """Свежий идентификатор не заблокирован."""
    limiter = InMemoryRateLimiter()
    assert await limiter.is_locked("login", "alice@example.com") is False
    assert await limiter.get_remaining_lockout("login", "alice@example.com") is None


async def test_lockout_after_max_attempts() -> None:
    """После N неудачных попыток — lockout."""
    limiter = InMemoryRateLimiter()
    identifier = "bob@example.com"
    scope = "login"
    max_attempts = limiter._lockout_params[scope].max_attempts  # noqa: SLF001

    for i in range(max_attempts - 1):
        await limiter.record_failure(scope, identifier)
        assert not await limiter.is_locked(scope, identifier), (
            f"не должно блокировать на {i + 1} попытке"
        )

    # N-я попытка — lockout
    await limiter.record_failure(scope, identifier)
    assert await limiter.is_locked(scope, identifier) is True

    remaining = await limiter.get_remaining_lockout(scope, identifier)
    assert remaining is not None
    assert 0 < remaining <= limiter._lockout_params[scope].base_lockout_seconds  # noqa: SLF001


async def test_success_resets_counter() -> None:
    """Успех сбрасывает счётчик."""
    limiter = InMemoryRateLimiter()
    identifier = "carol@example.com"
    scope = "login"

    for _ in range(limiter._lockout_params[scope].max_attempts - 1):  # noqa: SLF001
        await limiter.record_failure(scope, identifier)

    await limiter.record_success(scope, identifier)

    # Счётчик сброшен — следующая неудача не блокирует
    await limiter.record_failure(scope, identifier)
    assert not await limiter.is_locked(scope, identifier)


async def test_lockout_different_identifiers_isolated() -> None:
    """Lockout одного идентификатора не влияет на другой."""
    limiter = InMemoryRateLimiter()
    scope = "login"
    max_attempts = limiter._lockout_params[scope].max_attempts  # noqa: SLF001

    for _ in range(max_attempts):
        await limiter.record_failure(scope, "victim@example.com")

    assert await limiter.is_locked(scope, "victim@example.com") is True
    assert await limiter.is_locked(scope, "other@example.com") is False


# ═══════════════════════════════════════════════════════════════════════════
# Lockout: scope-изоляция
# ═══════════════════════════════════════════════════════════════════════════


async def test_login_and_mfa_scopes_isolated() -> None:
    """Lockout в scope="login" не влияет на scope="mfa" для того же identifier."""
    limiter = InMemoryRateLimiter()
    identifier = "user_42"

    # Исчерпываем login
    max_login = limiter._lockout_params["login"].max_attempts  # noqa: SLF001
    for _ in range(max_login):
        await limiter.record_failure("login", identifier)

    assert await limiter.is_locked("login", identifier) is True
    # MFA не тронут
    assert await limiter.is_locked("mfa", identifier) is False


async def test_mfa_uses_its_own_params() -> None:
    """Для scope="mfa" применяются отдельные max_attempts/lockout."""
    limiter = InMemoryRateLimiter()
    identifier = "user_43"

    login_params = limiter._lockout_params["login"]  # noqa: SLF001
    mfa_params = limiter._lockout_params["mfa"]  # noqa: SLF001

    # В Settings mfa строже login (5 vs 10)
    assert mfa_params.max_attempts < login_params.max_attempts

    # После mfa_params.max_attempts попыток — mfa заблокирован,
    # login — нет (он ещё не исчерпал свой лимит).
    for _ in range(mfa_params.max_attempts):
        await limiter.record_failure("mfa", identifier)

    assert await limiter.is_locked("mfa", identifier) is True
    assert await limiter.is_locked("login", identifier) is False


# ═══════════════════════════════════════════════════════════════════════════
# Quota
# ═══════════════════════════════════════════════════════════════════════════


async def test_quota_allows_within_limit() -> None:
    """Первые N запросов проходят, N+1 — нет."""
    limiter = InMemoryRateLimiter()

    for i in range(3):
        allowed = await limiter.consume_quota(
            "reset", "user@example.com", limit=3, window_seconds=3600
        )
        assert allowed is True, f"запрос {i + 1} должен быть разрешён"

    # 4-й — превышение
    allowed = await limiter.consume_quota(
        "reset", "user@example.com", limit=3, window_seconds=3600
    )
    assert allowed is False


async def test_quota_resets_after_window() -> None:
    """После истечения окна счётчик сбрасывается."""
    limiter = InMemoryRateLimiter()
    identifier = "user@example.com"

    # Исчерпываем
    for _ in range(3):
        await limiter.consume_quota(
            "reset", identifier, limit=3, window_seconds=1
        )
    assert await limiter.consume_quota(
        "reset", identifier, limit=3, window_seconds=1
    ) is False

    # Ждём окно (>1 сек)
    import asyncio

    await asyncio.sleep(1.1)

    # Окно истекло — снова разрешено
    allowed = await limiter.consume_quota(
        "reset", identifier, limit=3, window_seconds=1
    )
    assert allowed is True


async def test_quota_scope_isolation() -> None:
    """Квоты verify и reset независимы."""
    limiter = InMemoryRateLimiter()

    # Исчерпываем verify
    for _ in range(3):
        await limiter.consume_quota(
            "verify", "user_1", limit=3, window_seconds=3600
        )
    assert await limiter.consume_quota(
        "verify", "user_1", limit=3, window_seconds=3600
    ) is False

    # reset не тронут
    assert await limiter.consume_quota(
        "reset", "user_1", limit=3, window_seconds=3600
    ) is True


async def test_quota_identifier_isolation() -> None:
    """Квоты разных identifier'ов независимы."""
    limiter = InMemoryRateLimiter()

    for _ in range(3):
        await limiter.consume_quota(
            "reset", "a@example.com", limit=3, window_seconds=3600
        )

    # b@example.com не исчерпан
    assert await limiter.consume_quota(
        "reset", "b@example.com", limit=3, window_seconds=3600
    ) is True


# ═══════════════════════════════════════════════════════════════════════════
# Backoff
# ═══════════════════════════════════════════════════════════════════════════


async def test_exponential_backoff() -> None:
    """Каждое "нарушение" (max_attempts попыток) удваивает lockout."""
    limiter = InMemoryRateLimiter()
    identifier = "dave@example.com"
    scope = "login"

    max_attempts = limiter._lockout_params[scope].max_attempts  # noqa: SLF001

    for _ in range(max_attempts):
        await limiter.record_failure(scope, identifier)

    entry = limiter._lockouts[(scope, identifier)]  # noqa: SLF001
    assert entry.locked_until is not None

    for _ in range(max_attempts):
        await limiter.record_failure(scope, identifier)

    assert entry.failed_attempts == 2 * max_attempts


async def test_backoff_capped() -> None:
    """Lockout не превышает rate_limit_max_lockout_seconds."""
    max_lockout = 86400
    result = _compute_lockout_seconds(
        failed_attempts=100,
        max_attempts=10,
        base_lockout_seconds=300,
        max_lockout_seconds=max_lockout,
    )
    assert result == max_lockout


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════


async def test_get_rate_limiter_singleton() -> None:
    """get_rate_limiter возвращает тот же инстанс."""
    a = get_rate_limiter()
    b = get_rate_limiter()
    assert a is b


# ═══════════════════════════════════════════════════════════════════════════
# Интеграция: /auth/login → 423
# ═══════════════════════════════════════════════════════════════════════════


async def test_login_lockout_returns_423(client) -> None:
    """
    После max_attempts неудачных логинов — 423 Locked.

    Не требует существующего пользователя: rate limiter работает
    на identifier (email), а не на user_id. Так мы не раскрываем
    существование пользователя через rate limiting.
    """
    limiter = get_rate_limiter()
    identifier = "lockme@example.com"

    for _ in range(10):
        await limiter.record_failure("login", identifier)

    assert await limiter.is_locked("login", identifier)

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": identifier, "password": "any-password-here-1234"},
    )
    assert r.status_code == 423
    body = r.json()
    assert body["type"].endswith("/account-locked")
    assert "retry_after" in body