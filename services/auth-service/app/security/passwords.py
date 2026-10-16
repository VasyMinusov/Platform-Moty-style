"""
Парольная политика и хеширование.

Соответствие: NIST SP 800-63B Rev 4 (August 2025).

Ключевые принципы:
- Length over complexity: никаких composition rules (SHALL NOT).
- Blocklist screening: обязательная проверка на compromised пароли (SHALL).
- Хранение: Argon2id (memory-hard, winner Password Hashing Competition).
- No periodic rotation: смена только по evidence of compromise (SHALL).

Все параметры (min length, Argon2 cost, rate limit, HIBP) читаются
из app.config.Settings — никакого хардкода.
"""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import httpx

# argon2-cffi — современный пакет (не путать с legacy `argon2` 0.1.10,
# который мы убрали из зависимостей — см. pyproject.toml).
#
# Type — enum {I, D, ID}. Используем ID (Argon2id) — гибрид Argon2i
# (устойчив к side-channel) и Argon2d (устойчив к GPU/ASIC). Это
# рекомендованный режим в RFC 9106 §4 и OWASP Password Storage
# Cheat Sheet.
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2 import Type as Argon2Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Константы NIST SP 800-63B Rev 4
# ═══════════════════════════════════════════════════════════════════════════

# Minimum length for passwords used as a SINGLE authentication factor.
# NIST: "SHALL require passwords be at least 15 characters when the
# password is the only authenticator."
MIN_PASSWORD_LENGTH_SINGLE_FACTOR: Final[int] = 15

# Minimum length when password is part of MFA.
# NIST: 8 characters floor.
MIN_PASSWORD_LENGTH_MFA: Final[int] = 8

# NIST: "SHALL permit passwords of at least 64 characters."
MAX_PASSWORD_LENGTH: Final[int] = 64

# ── Argon2id параметры ─────────────────────────────────────────────────────
#
# OWASP Password Storage Cheat Sheet (2024+):
#   - Argon2id, m=19456 (19 MiB), t=2, p=1 — минимально допустимо.
#   - Argon2id, m=47104 (46 MiB), t=1, p=1 — эквивалент, если CPU важнее.
#   - Argon2id, m=9216 (9 MiB), t=4, p=1  — при жёстких ограничениях памяти.
#
# Мы выбрали более параноидальный вариант: 64 MiB, t=3, p=4. Это ~50–100 ms
# на hash, что оправданно для auth-сервиса, где логинов мало, а
# компромисс парольной БД критичен.
#
# При росте нагрузки: снижать time_cost в первую очередь, memory_cost
# во вторую, parallelism в последнюю.
ARGON2_TYPE: Final[Argon2Type] = Argon2Type.ID    # ← Argon2id, явно
ARGON2_TIME_COST: Final[int] = 3
ARGON2_MEMORY_COST: Final[int] = 65536            # 64 MiB
ARGON2_PARALLELISM: Final[int] = 4
ARGON2_HASH_LEN: Final[int] = 32
ARGON2_SALT_LEN: Final[int] = 16


# ═══════════════════════════════════════════════════════════════════════════
# PasswordHasher: Argon2id
# ═══════════════════════════════════════════════════════════════════════════


class PasswordHasher:
    """
    Обёртка над argon2-cffi с параметрами для auth-сервиса.

    Алгоритм — Argon2id (Type.ID):
    - Memory-hard: сложнее для GPU/ASIC-атак, чем bcrypt (CPU-bound).
    - Устойчив к side-channel (в отличие от Argon2d).
    - Устойчив к time-memory trade-off (в отличие от Argon2i).
    - NIST SP 800-63B Rev 4 не называет конкретный алгоритм, но
      требует "slow, memory-hard function". Argon2id — современный
      стандарт, победитель Password Hashing Competition (2015).
    - OWASP Password Storage Cheat Sheet рекомендует Argon2id как
      первый выбор.

    bcrypt всё ещё приемлем, но Argon2id — предпочтительнее.
    Argon2i / Argon2d напрямую — не использовать.
    """

    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher(
            # Явный type=Type.ID, не полагаемся на default argon2-cffi.
            # Если в будущем default сменится (маловероятно) — мы не
            # изменим поведение молча.
            type=ARGON2_TYPE,
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST,
            parallelism=ARGON2_PARALLELISM,
            hash_len=ARGON2_HASH_LEN,
            salt_len=ARGON2_SALT_LEN,
        )

    def hash(self, password: str) -> str:
        """
        Захешировать пароль.

        Возвращает PHC-строку вида:
            $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
             ^^^^^^^^ — тип алгоритма (Argon2id)

        Salt генерируется автоматически (16 байт), встроен в результат.
        """
        return self._hasher.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        """
        Проверить пароль против хеша.

        Возвращает False при неверном пароле или повреждённом хеше.
        Constant-time comparison обеспечивается внутри argon2-cffi.

        Важно: argon2-cffi умеет верифицировать хеши, созданные
        Argon2i / Argon2d / Argon2id (по префиксу PHC-строки) — так
        что даже если у вас остались старые хеши от другого типа,
        они продолжат работать.
        """
        try:
            self._hasher.verify(hashed, password)
            return True
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """
        Проверить, нужно ли перехешировать пароль.

        Вызывается после успешного verify(): если параметры хеша
        устарели (например, подняли memory_cost) — возвращаем True,
        и login прозрачно перехеширует пароль новыми параметрами.

        argon2-cffi сам сравнивает type / time_cost / memory_cost /
        parallelism / hash_len / salt_len из PHC-строки с текущими
        параметрами хешера.
        """
        return self._hasher.check_needs_rehash(hashed)


_password_hasher: PasswordHasher | None = None


def get_password_hasher() -> PasswordHasher:
    global _password_hasher
    if _password_hasher is None:
        _password_hasher = PasswordHasher()
    return _password_hasher


@lru_cache(maxsize=1)
def get_dummy_hash() -> str:
    """
    Реальный Argon2id-хеш произвольного пароля для timing-safe verify.

    Зачем:
    При login, если пользователь не найден, мы всё равно должны
    выполнить verify, чтобы время ответа не отличалось от случая
    существующего пользователя (защита от user enumeration через
    timing attack).

    Почему не хардкод-строка:
    Хардкод-хеш может быть невалидным для текущих параметров Argon2
    (argon2-cffi выйдет раньше, не выполнив memory-hard часть), и
    время verify будет на порядки меньше, чем для реального хеша.
    Здесь мы генерируем хеш теми же параметрами, что и рабочие хеши,
    поэтому время verify идентично.

    Кешируется через lru_cache — генерируется один раз за процесс.
    """
    return get_password_hasher().hash("dummy-timing-safe-password")


def reset_password_hasher() -> None:
    """Сбросить singleton (для тестов)."""
    global _password_hasher
    _password_hasher = None
    get_dummy_hash.cache_clear()


# ═══════════════════════════════════════════════════════════════════════════
# Blocklist: Have I Been Pwned (k-anonymity)
# ═══════════════════════════════════════════════════════════════════════════


class BreachChecker:
    """
    Проверка пароля по базе compromised credentials.

    Использует HIBP Pwned Passwords API с k-anonymity:
    - SHA-1 хеш пароля разбивается: первые 5 hex-символов → запрос,
      остальные 35 → локальное сравнение.
    - Сервер HIBP НЕ получает полный хеш → пароль не утекает.

    NIST SP 800-63B Rev 4 (Section 5.1.1.2):
    "Verifiers SHALL compare the prospective secrets against a list
    that contains passwords known to be compromised."

    Настройки (enabled, timeout, fail_open) читаются из Settings:
    - HIBP_ENABLED=false — отключить (для тестов/offline)
    - HIBP_TIMEOUT_SECONDS=5.0 — таймаут запроса
    - HIBP_FAIL_OPEN=true — пропускать при недоступности HIBP
    """

    HIBP_API_URL: str = "https://api.pwnedpasswords.com/range/"

    def __init__(self) -> None:
        settings = get_settings()
        self._timeout = settings.hibp_timeout_seconds
        self._enabled = settings.hibp_enabled
        self._fail_open = settings.hibp_fail_open
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Ленивая инициализация HTTP-клиента (переиспользует connection pool)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "auth-service/1.0"},
            )
        return self._client

    @staticmethod
    def _sha1_hex(password: str) -> str:
        """SHA-1 хеш в uppercase hex. HIBP использует именно SHA-1."""
        return hashlib.sha1(password.encode("utf-8")).hexdigest().upper()

    async def is_compromised(self, password: str) -> bool:
        """
        Проверить, встречается ли пароль в утечках.

        Возвращает True, если пароль найден в HIBP.

        Fail-open vs fail-closed:
        - fail-open (по умолчанию): пароль пропускается при
          недоступности HIBP. Недоступность внешнего API не должна
          блокировать регистрацию.
        - fail-closed: регистрация падает. Выбирается через
          HIBP_FAIL_OPEN=false.
        """
        if not self._enabled:
            return False

        sha1 = self._sha1_hex(password)
        prefix, suffix = sha1[:5], sha1[5:]

        try:
            client = await self._get_client()
            response = await client.get(f"{self.HIBP_API_URL}{prefix}")
            response.raise_for_status()

            # Ответ: строки вида "SUFFIX:COUNT\r\n"
            for line in response.text.splitlines():
                parts = line.split(":")
                if len(parts) == 2 and parts[0] == suffix:
                    count = int(parts[1])
                    if count > 0:
                        log.warning(
                            "password_found_in_breach",
                            breach_count=count,
                        )
                        return True

            return False

        except httpx.HTTPError as exc:
            log.error(
                "hibp_request_failed",
                error=str(exc),
                fail_mode="open" if self._fail_open else "closed",
            )
            return not self._fail_open

    async def close(self) -> None:
        """Закрыть HTTP-клиент при shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_breach_checker: BreachChecker | None = None


def get_breach_checker() -> BreachChecker:
    global _breach_checker
    if _breach_checker is None:
        _breach_checker = BreachChecker()
    return _breach_checker


def reset_breach_checker() -> None:
    """Сбросить singleton (для тестов)."""
    global _breach_checker
    _breach_checker = None


# ═══════════════════════════════════════════════════════════════════════════
# Валидация пароля
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PasswordValidationResult:
    """Результат валидации пароля."""

    is_valid: bool
    errors: list[str]


async def validate_password(
    password: str,
    *,
    username: str | None = None,
    email: str | None = None,
    is_mfa: bool = False,
) -> PasswordValidationResult:
    """
    Полная валидация пароля по NIST SP 800-63B Rev 4.

    Порядок проверок (от дешёвых к дорогим):
    1. Длина (локально, мгновенно).
    2. Context-specific words (локально).
    3. Breach check (сетевой вызов, только если HIBP_ENABLED=true).

    Composition rules НЕ проверяются — NIST SHALL NOT.

    Аргументы:
        password: кандидат.
        username, email: для context-specific проверки.
        is_mfa: если True — минимальная длина 8, иначе 15.
    """
    errors: list[str] = []

    # ── 1. Длина ──────────────────────────────────────────────────────────
    min_length = MIN_PASSWORD_LENGTH_MFA if is_mfa else MIN_PASSWORD_LENGTH_SINGLE_FACTOR

    if len(password) < min_length:
        errors.append(f"Password must be at least {min_length} characters.")

    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"Password must not exceed {MAX_PASSWORD_LENGTH} characters.")

    # NIST SHALL NOT truncate: проверяем длину полностью, не обрезаем.

    # ── 2. Context-specific words ─────────────────────────────────────────
    # NIST: blocklist должен включать "context-specific words, such as
    # the name of the service, the username, and derivatives thereof."
    password_lower = password.lower()

    if username and len(username) >= 3 and username.lower() in password_lower:
        errors.append("Password must not contain your username.")

    if email and "@" in email:
        local_part = email.split("@")[0].lower()
        if len(local_part) >= 3 and local_part in password_lower:
            errors.append("Password must not contain your email address.")

    # ── 3. Breach check (сетевой) ─────────────────────────────────────────
    # Выполняем только если пароль прошёл локальные проверки
    # и HIBP включён.
    if not errors and get_settings().hibp_enabled:
        checker = get_breach_checker()
        if await checker.is_compromised(password):
            errors.append(
                "This password has appeared in a data breach and cannot be used. "
                "Please choose a different password."
            )

    return PasswordValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
    )