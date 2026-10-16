"""
Rate limiter: lockout для failed auth + quota для email-endpoints.

Два независимых режима за одним Protocol:

1. **Lockout** (failed attempts с экспоненциальным backoff).
   NIST SP 800-63B Rev 4 §5.2.2:
   "Verifiers SHALL implement rate limiting on failed authentication
   attempts."
   Применяется к:
     - /auth/login              (scope="login")
     - /auth/mfa/verify         (scope="mfa")
     - /users/me/mfa/verify     (scope="mfa")
     - /users/me/mfa/disable    (scope="mfa")

2. **Quota** (N запросов в скользящем окне).
   NIST §5.1.1.2 + OWASP A07:2025: ограничение частоты запросов писем
   (email-bombing).
   Применяется к:
     - /auth/verify-email              (scope="verify")
     - /auth/password-reset/request    (scope="reset")
     - min interval между reset-письмами (scope="reset_interval")

**Изоляция scope'ов.** Ключи в Redis / dict:
    auth:rl:{scope}:{identifier}:failures     — счётчик (INCR)
    auth:rl:{scope}:{identifier}:locked_until — Unix timestamp
    auth:rl:{scope}:{identifier}:quota        — счётчик окна (INCR)
Счётчики login и mfa / reset независимы: подбор пароля и подбор TOTP —
разные атаки, не должны пересекаться.

**Две реализации за одним Protocol:**
- InMemoryRateLimiter — dev / single-process / тесты.
- RedisRateLimiter    — prod / multi-worker / multi-instance.

Выбор — через Settings.rate_limit_backend. В тестах (conftest.py)
принудительно ставим "memory", чтобы не требовать Redis.

**Почему не оставляем только in-memory:**
- При `uvicorn --workers 4` каждый воркер держит свой dict.
  Счётчики не синхронизируются: 10 попыток через воркер A → lockout,
  11-я через воркер B → успех. Rate limit не работает.
- При горизонтальном масштабировании (несколько pod'ов) — то же.

**Почему не оставляем только Redis:**
- Dev-разработчику не нужен Redis, чтобы запустить сервис.
- Тестам не нужен внешний сервис (изоляция).
"""

import time
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import redis.asyncio as aioredis

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# Префикс ключей в Redis. Изолирует от других сервисов, использующих
# тот же Redis (чтобы namespace не пересекались).
_KEY_PREFIX: Final[str] = "auth:rl:"


# Типы scope'ов — Literal, чтобы mypy ловил опечатки в роутерах.
# Lockout-scope (record_failure/is_locked/get_remaining_lockout).
LockoutScope = Literal["login", "mfa"]

# Quota-scope (consume_quota).
QuotaScope = Literal["verify", "reset", "reset_interval"]


def _now() -> float:
    """Unix-timestamp с миллисекундной точностью. Отдельная функция — для тестов."""
    return time.time()


# ═══════════════════════════════════════════════════════════════════════════
# Protocol
# ═══════════════════════════════════════════════════════════════════════════


class RateLimiter(Protocol):
    """
    Интерфейс rate limiter.

    Все методы async: даже in-memory может переехать на async backend
    без изменения вызывающего кода.
    """

    # ── Lockout ───────────────────────────────────────────────────────────

    async def is_locked(self, scope: LockoutScope, identifier: str) -> bool:
        """Проверить, заблокирован ли идентификатор в данном scope."""
        ...

    async def record_failure(self, scope: LockoutScope, identifier: str) -> None:
        """Зафиксировать неудачную попытку."""
        ...

    async def record_success(self, scope: LockoutScope, identifier: str) -> None:
        """Сбросить счётчики после успешной аутентификации."""
        ...

    async def get_remaining_lockout(
        self, scope: LockoutScope, identifier: str
    ) -> int | None:
        """Сколько секунд осталось до разблокировки (или None)."""
        ...

    # ── Quota ─────────────────────────────────────────────────────────────

    async def consume_quota(
        self,
        scope: QuotaScope,
        identifier: str,
        *,
        limit: int,
        window_seconds: int = 3600,
    ) -> bool:
        """
        Атомарно «съесть» одну единицу квоты.

        Возвращает True, если запрос разрешён (в пределах лимита),
        False — если лимит исчерпан. Окно скользящее от первого запроса.
        """
        ...

    async def clear_quota(self, scope: QuotaScope, identifier: str) -> None:
        """
        Сбросить quota-счётчик для (scope, identifier).

        Применение:
        - Тесты: обойти min-interval, не трогая hourly-quota.
        - Admin: сбросить пользователю исчерпанную квоту (вручную).
        - Recovery: после подтверждения, что пользователь — не абьюзер.
        """
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _LockoutParams:
    """Параметры lockout для одного scope."""

    max_attempts: int
    base_lockout_seconds: int
    max_lockout_seconds: int


def _compute_lockout_seconds(
    failed_attempts: int,
    max_attempts: int,
    base_lockout_seconds: int,
    max_lockout_seconds: int,
) -> int:
    """
    Экспоненциальный backoff: base * 2^(violations - 1), с cap.

    violations = failed_attempts // max_attempts.
    Пример при base=300, max=10:
       10-я попытка → violations=1, lockout=300 сек (5 мин)
       20-я попытка → violations=2, lockout=600 сек (10 мин)
       30-я попытка → violations=3, lockout=1200 сек (20 мин)
       ...
    Cap: rate_limit_max_lockout_seconds (по умолчанию 86400 = 24 ч).
    """
    violations = failed_attempts // max_attempts
    if violations < 1:
        violations = 1
    # 1 << n эквивалентно 2 ** n, но гарантирует int для mypy.
    multiplier = 1 << (violations - 1)
    raw = base_lockout_seconds * multiplier
    return min(raw, max_lockout_seconds)


def _build_lockout_params() -> dict[LockoutScope, _LockoutParams]:
    """Собрать параметры lockout для всех scope'ов из Settings."""
    settings = get_settings()
    return {
        "login": _LockoutParams(
            max_attempts=settings.rate_limit_max_attempts,
            base_lockout_seconds=settings.rate_limit_lockout_seconds,
            max_lockout_seconds=settings.rate_limit_max_lockout_seconds,
        ),
        "mfa": _LockoutParams(
            max_attempts=settings.rate_limit_mfa_verify_max_attempts,
            base_lockout_seconds=settings.rate_limit_mfa_verify_lockout_seconds,
            max_lockout_seconds=settings.rate_limit_max_lockout_seconds,
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# In-memory backend (dev / tests)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class _MemoryLockoutEntry:
    """Состояние lockout для одного (scope, identifier)."""

    failed_attempts: int = 0
    locked_until: float | None = None  # Unix timestamp


@dataclass
class _MemoryQuotaEntry:
    """Состояние quota-окна для одного (scope, identifier)."""

    count: int = 0
    window_start: float = 0.0
    window_seconds: int = 3600


class InMemoryRateLimiter:
    """
    In-memory rate limiter.

    НЕ подходит для multi-worker / multi-instance деплоя.
    Используется только в dev и тестах.
    """

    def __init__(self) -> None:
        self._lockout_params: dict[LockoutScope, _LockoutParams] = _build_lockout_params()
        self._lockouts: dict[tuple[LockoutScope, str], _MemoryLockoutEntry] = {}
        self._quotas: dict[tuple[QuotaScope, str], _MemoryQuotaEntry] = {}

    def _params(self, scope: LockoutScope) -> _LockoutParams:
        # scope типизирован Literal — KeyError возможен только при
        # рассинхронизации Literal и словаря. Это баг, а не runtime-кейс.
        return self._lockout_params[scope]

    # ── Lockout ───────────────────────────────────────────────────────────

    async def is_locked(self, scope: LockoutScope, identifier: str) -> bool:
        entry = self._lockouts.get((scope, identifier))
        if entry is None or entry.locked_until is None:
            return False

        if _now() >= entry.locked_until:
            # Lockout истёк — сбрасываем.
            del self._lockouts[(scope, identifier)]
            return False

        return True

    async def record_failure(self, scope: LockoutScope, identifier: str) -> None:
        key = (scope, identifier)
        entry = self._lockouts.setdefault(key, _MemoryLockoutEntry())
        entry.failed_attempts += 1

        params = self._params(scope)
        if entry.failed_attempts >= params.max_attempts:
            lockout_seconds = _compute_lockout_seconds(
                entry.failed_attempts,
                params.max_attempts,
                params.base_lockout_seconds,
                params.max_lockout_seconds,
            )
            entry.locked_until = _now() + lockout_seconds

            log.warning(
                "rate_limit_lockout",
                scope=scope,
                identifier=identifier,
                failed_attempts=entry.failed_attempts,
                lockout_seconds=lockout_seconds,
                backend="memory",
            )

    async def record_success(self, scope: LockoutScope, identifier: str) -> None:
        self._lockouts.pop((scope, identifier), None)

    async def get_remaining_lockout(
        self, scope: LockoutScope, identifier: str
    ) -> int | None:
        entry = self._lockouts.get((scope, identifier))
        if entry is None or entry.locked_until is None:
            return None
        return max(0, int(entry.locked_until - _now()))

    # ── Quota ─────────────────────────────────────────────────────────────

    async def consume_quota(
        self,
        scope: QuotaScope,
        identifier: str,
        *,
        limit: int,
        window_seconds: int = 3600,
    ) -> bool:
        """
        Атомарно «съесть» одну единицу квоты.

        Окно скользящее от первого запроса: при первом вызове
        фиксируется window_start, по истечении window_seconds
        счётчик сбрасывается.
        """
        key = (scope, identifier)
        now = _now()
        entry = self._quotas.get(key)

        if entry is None or (now - entry.window_start) >= entry.window_seconds:
            entry = _MemoryQuotaEntry(
                count=0, window_start=now, window_seconds=window_seconds
            )
            self._quotas[key] = entry

        entry.count += 1
        allowed = entry.count <= limit

        if not allowed:
            log.warning(
                "rate_limit_quota_exceeded",
                scope=scope,
                identifier=identifier,
                count=entry.count,
                limit=limit,
                window_seconds=window_seconds,
                backend="memory",
            )
        return allowed

    async def clear_quota(self, scope: QuotaScope, identifier: str) -> None:
        """Удалить запись quota. Следующий consume_quota начнёт новое окно."""
        self._quotas.pop((scope, identifier), None)


# ═══════════════════════════════════════════════════════════════════════════
# Redis backend (prod)
# ═══════════════════════════════════════════════════════════════════════════


class RedisRateLimiter:
    """
    Distributed rate limiter на Redis.

    Схема ключей (scope изолирует счётчики):
        {prefix}{scope}:{identifier}:failures     — счётчик (INCR)
        {prefix}{scope}:{identifier}:locked_until — Unix timestamp
        {prefix}{scope}:{identifier}:quota        — счётчик окна (INCR)

    Почему timestamp для lockout, а не флаг:
    - get_remaining_lockout должен вернуть точное число секунд.
    - TTL на ключе + сравнение timestamp = защита от гонок: если два
      воркера одновременно словили lockout, оба SET перезапишут, но
      из-за одинакового now() результат один.
    """

    def __init__(self, client: aioredis.Redis) -> None:
        settings = get_settings()
        self._client = client
        self._lockout_params: dict[LockoutScope, _LockoutParams] = _build_lockout_params()
        self._ttl = settings.rate_limit_redis_ttl

    def _params(self, scope: LockoutScope) -> _LockoutParams:
        return self._lockout_params[scope]

    @staticmethod
    def _failures_key(scope: LockoutScope, identifier: str) -> str:
        return f"{_KEY_PREFIX}{scope}:{identifier}:failures"

    @staticmethod
    def _locked_key(scope: LockoutScope, identifier: str) -> str:
        return f"{_KEY_PREFIX}{scope}:{identifier}:locked_until"

    @staticmethod
    def _quota_key(scope: QuotaScope, identifier: str) -> str:
        return f"{_KEY_PREFIX}{scope}:{identifier}:quota"

    # ── Lockout ───────────────────────────────────────────────────────────

    async def is_locked(self, scope: LockoutScope, identifier: str) -> bool:
        raw = await self._client.get(self._locked_key(scope, identifier))
        if raw is None:
            return False

        locked_until = float(raw)
        if _now() >= locked_until:
            # Истекло, но ключ ещё не удалён (маловероятно — TTL).
            await self._client.delete(self._locked_key(scope, identifier))
            return False

        return True

    async def record_failure(self, scope: LockoutScope, identifier: str) -> None:
        failures_key = self._failures_key(scope, identifier)
        failures = await self._client.incr(failures_key)
        # TTL ставим при каждом инкременте — это продлевает окно.
        await self._client.expire(failures_key, self._ttl)

        params = self._params(scope)
        if failures >= params.max_attempts:
            lockout_seconds = _compute_lockout_seconds(
                int(failures),
                params.max_attempts,
                params.base_lockout_seconds,
                params.max_lockout_seconds,
            )
            locked_until = _now() + lockout_seconds
            await self._client.set(
                self._locked_key(scope, identifier),
                locked_until,
                ex=lockout_seconds,
            )

            log.warning(
                "rate_limit_lockout",
                scope=scope,
                identifier=identifier,
                failed_attempts=int(failures),
                lockout_seconds=lockout_seconds,
                backend="redis",
            )

    async def record_success(self, scope: LockoutScope, identifier: str) -> None:
        await self._client.delete(
            self._failures_key(scope, identifier),
            self._locked_key(scope, identifier),
        )

    async def get_remaining_lockout(
        self, scope: LockoutScope, identifier: str
    ) -> int | None:
        raw = await self._client.get(self._locked_key(scope, identifier))
        if raw is None:
            return None
        remaining = float(raw) - _now()
        return max(0, int(remaining))

    # ── Quota ─────────────────────────────────────────────────────────────

    async def consume_quota(
        self,
        scope: QuotaScope,
        identifier: str,
        *,
        limit: int,
        window_seconds: int = 3600,
    ) -> bool:
        """
        Атомарный INCR + EXPIRE (окно от первого запроса).

        EXPIRE ставится ТОЛЬКО при первом INCR (count == 1): иначе
        каждое последующее обращение продлевало бы окно, и «3 в час»
        превратилось бы в «3 в час с момента последнего запроса».
        """
        key = self._quota_key(scope, identifier)
        count = await self._client.incr(key)
        if count == 1:
            # Первый инкремент — стартуем окно.
            await self._client.expire(key, window_seconds)

        allowed = count <= limit
        if not allowed:
            log.warning(
                "rate_limit_quota_exceeded",
                scope=scope,
                identifier=identifier,
                count=int(count),
                limit=limit,
                window_seconds=window_seconds,
                backend="redis",
            )
        return allowed

    async def clear_quota(self, scope: QuotaScope, identifier: str) -> None:
        """Удалить ключ quota из Redis."""
        await self._client.delete(self._quota_key(scope, identifier))


# ═══════════════════════════════════════════════════════════════════════════
# Factory / lifecycle
# ═══════════════════════════════════════════════════════════════════════════

_rate_limiter: RateLimiter | None = None
_redis_client: aioredis.Redis | None = None


async def init_rate_limiter() -> RateLimiter:
    """
    Инициализировать rate limiter (fail-fast).

    Вызывается из lifespan при startup. В Redis-режиме делает PING,
    чтобы упасть сразу, если Redis недоступен.

    Возвращает singleton — идемпотентно.
    """
    global _rate_limiter, _redis_client

    if _rate_limiter is not None:
        return _rate_limiter

    settings = get_settings()

    if settings.rate_limit_backend == "redis":
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
        )
        # Fail-fast: ping, чтобы упасть на startup при недоступном Redis.
        await _redis_client.ping()
        _rate_limiter = RedisRateLimiter(_redis_client)
        log.info("rate_limiter_initialized", backend="redis", host=settings.redis_host)
    else:
        _rate_limiter = InMemoryRateLimiter()
        log.info("rate_limiter_initialized", backend="memory")

    return _rate_limiter


async def shutdown_rate_limiter() -> None:
    """
    Закрыть соединения rate limiter при shutdown.

    Для Redis — закрывает пул соединений. Для memory — no-op.
    """
    global _rate_limiter, _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None

    _rate_limiter = None


def get_rate_limiter() -> RateLimiter:
    """
    Получить rate limiter.

    ВАЖНО: до первого вызова init_rate_limiter() (в lifespan) —
    бросает RuntimeError. Это защита от использования до startup.
    """
    if _rate_limiter is None:
        raise RuntimeError(
            "Rate limiter not initialized. "
            "Call init_rate_limiter() in app lifespan."
        )
    return _rate_limiter


def reset_rate_limiter() -> None:
    """
    Сбросить singleton (для тестов).

    Не закрывает Redis-соединение — для этого shutdown_rate_limiter().
    Просто забывает ссылку, чтобы следующий вызов init_rate_limiter()
    создал свежий экземпляр.
    """
    global _rate_limiter, _redis_client
    _rate_limiter = None
    _redis_client = None
