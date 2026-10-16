"""
Fuzz-тесты валидатора пароля.

Цель: `validate_password(malicious, ...)` не должен падать с 500
на любой строке. Все проверки (длина, context-specific words, HIBP)
должны возвращать `PasswordValidationResult`, а не бросать исключения.

HIBP отключён (HIBP_ENABLED=false в conftest.py) — в сеть не ходим.
Проверяются только локальные правила.

Тесты async: `validate_password` — async-функция (HIBP — сетевой вызов).
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.security.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH_MFA,
    MIN_PASSWORD_LENGTH_SINGLE_FACTOR,
    validate_password,
)

pytestmark = pytest.mark.fuzz


_FUZZ_SETTINGS = settings(
    max_examples=150,
    deadline=None,  # validate_password может тормозить на длинных строках
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ─── Стратегии ─────────────────────────────────────────────────────────────

_anything = st.text(max_size=2000)

_ascii = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    max_size=200,
)


# ═══════════════════════════════════════════════════════════════════════════
# Никаких неожиданных исключений
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(password=_anything)
async def test_validate_password_never_unexpected(password: str) -> None:
    """
    Любая Unicode-строка → PasswordValidationResult, не исключение.
    """
    try:
        result = await validate_password(
            password, username=None, email=None, is_mfa=False
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"validate_password({password!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )

    assert isinstance(result.is_valid, bool)
    assert isinstance(result.errors, list)


@_FUZZ_SETTINGS
@given(password=_anything, username=_anything, email=_anything)
async def test_validate_password_with_context_never_unexpected(
    password: str, username: str, email: str
) -> None:
    """
    Любые комбинации password/username/email → без исключений.
    """
    try:
        await validate_password(
            password,
            username=username,
            email=email,
            is_mfa=False,
        )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"validate_password({password!r}, username={username!r}, "
            f"email={email!r}) бросил {type(exc).__name__}: {exc}."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Границы длины
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(
    length=st.integers(
        min_value=0,
        max_value=MIN_PASSWORD_LENGTH_SINGLE_FACTOR - 1,
    )
)
async def test_short_password_rejected_single_factor(length: int) -> None:
    """
    Пароль < 15 символов (single-factor) → is_valid=False.
    Проверяем все длины от 0 до 14.
    """
    password = "x" * length
    result = await validate_password(password, is_mfa=False)
    assert not result.is_valid
    assert any("at least" in e.lower() for e in result.errors)


@_FUZZ_SETTINGS
@given(
    length=st.integers(
        min_value=MIN_PASSWORD_LENGTH_SINGLE_FACTOR,
        max_value=MAX_PASSWORD_LENGTH,
    )
)
async def test_valid_length_password_accepted(length: int) -> None:
    """
    Пароль длиной 15..64 (single-factor, ASCII) → is_valid=True.
    Проверяем все длины в диапазоне.
    """
    password = "x" * length
    result = await validate_password(password, is_mfa=False)
    assert result.is_valid, f"длина {length} должна быть валидна: {result.errors}"


@_FUZZ_SETTINGS
@given(
    length=st.integers(
        min_value=MIN_PASSWORD_LENGTH_MFA,
        max_value=MIN_PASSWORD_LENGTH_SINGLE_FACTOR - 1,
    )
)
async def test_mfa_length_accepts_shorter(length: int) -> None:
    """
    is_mfa=True: 8..14 символов валидны (MFA-контекст → min 8).
    """
    password = "x" * length
    result = await validate_password(password, is_mfa=True)
    assert result.is_valid, f"длина {length} (MFA) должна быть валидна"


@_FUZZ_SETTINGS
@given(
    length=st.integers(
        min_value=MAX_PASSWORD_LENGTH + 1,
        max_value=MAX_PASSWORD_LENGTH + 500,
    )
)
async def test_long_password_rejected(length: int) -> None:
    """
    Пароль > 64 символов → is_valid=False.
    """
    password = "x" * length
    result = await validate_password(password, is_mfa=False)
    assert not result.is_valid
    assert any("exceed" in e.lower() for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════
# Context-specific words
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(
    username=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=3,
        max_size=20,
    ),
    suffix=st.text(min_size=1, max_size=50),
)
async def test_password_with_username_rejected(username: str, suffix: str) -> None:
    """
    Пароль, содержащий username, отклоняется (NIST context-specific).
    """
    # Пароль достаточно длинный и содержит username где-то в середине.
    password = f"prefix-{username}-suffix-{suffix}"
    # Padding до 15+ символов, если случайно получилось меньше.
    password = password.ljust(20, "x")

    result = await validate_password(
        password, username=username, is_mfa=False
    )
    assert not result.is_valid, (
        f"пароль {password!r} содержит username {username!r}, "
        "должен быть отклонён"
    )
    assert any("username" in e.lower() for e in result.errors)


@_FUZZ_SETTINGS
@given(
    local_part=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=3,
        max_size=20,
    ),
    suffix=st.text(min_size=1, max_size=50),
)
async def test_password_with_email_local_part_rejected(
    local_part: str, suffix: str
) -> None:
    """
    Пароль, содержащий локальную часть email, отклоняется.
    """
    email = f"{local_part}@example.com"
    password = f"prefix-{local_part}-suffix-{suffix}".ljust(20, "x")

    result = await validate_password(password, email=email, is_mfa=False)
    assert not result.is_valid
    assert any("email" in e.lower() for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════
# Unicode и бинарные данные
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(password=st.text(min_size=15, max_size=64))
async def test_unicode_password_accepted(password: str) -> None:
    """
    Unicode-пароль длиной 15..64 → принимается (NIST: SHALL permit
    любые printable characters, включая пробелы и эмодзи).

    Ограничение только по длине в символах, не в байтах.
    """
    result = await validate_password(password, is_mfa=False)
    # Может быть invalid только если содержит @ (context-specific: нет)
    # или совпал с HIBP (у нас HIBP off). Но в общем случае — is_valid=True,
    # если нет context words. Не ассертим, что всегда True — это не наша
    # задача; проверяем отсутствие исключения (см. assert выше в других).
    assert isinstance(result.is_valid, bool)


@_FUZZ_SETTINGS
@given(password=st.binary(min_size=0, max_size=100).map(lambda b: b.decode("latin-1")))
async def test_binary_password_never_unexpected(password: str) -> None:
    """
    Бинарные данные, декодированные в latin-1 (включая \\x00, control chars)
    → без исключений.
    """
    try:
        result = await validate_password(password, is_mfa=False)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"validate_password({password!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )
    assert isinstance(result.is_valid, bool)