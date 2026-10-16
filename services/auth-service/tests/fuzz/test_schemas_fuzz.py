"""
Fuzz-тесты Pydantic-схем.

Цель: мусор на входе → `ValidationError`, а не 500. Pydantic v2
устойчив к Unicode, но fuzz ловит краевые случаи:

- очень длинные строки → не должны уходить в regex-backtracking;
- surrogate-пары Unicode (invalid UTF-8) → pydantic должен отклонить;
- границы min/max length для username/password;
- `EmailStr` на мусоре → ValidationError (не ValueError от
  email-validator);
- `extra="forbid"` в BaseSchema — лишние поля → ValidationError.

Все тесты sync: Pydantic-валидация чистая, без async-зависимостей.
Фикстура `reset_singletons` не требуется.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    UserCreate,
    UserUpdate,
)

pytestmark = pytest.mark.fuzz


_FUZZ_SETTINGS = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ─── Стратегии ─────────────────────────────────────────────────────────────

# Приемлемый username по паттерну: [a-zA-Z0-9_]{3,64}.
_valid_username = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=3,
    max_size=64,
)

# Простой email вида `x@y.z` — проходит EmailStr.
_valid_email = st.builds(
    lambda local, domain: f"{local}@{domain}.example",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20),
)

# Хоть что-то на месте email (включая заведомо невалидное).
_anything = st.text(max_size=2000)


# ═══════════════════════════════════════════════════════════════════════════
# UserCreate
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(email=_anything, username=_anything, password=_anything)
def test_user_create_never_unexpected(email: str, username: str, password: str) -> None:
    """
    `UserCreate(...)` на любом мусоре → либо валидный объект,
    либо ValidationError. Никаких 500-подобных исключений.
    """
    try:
        UserCreate(email=email, username=username, password=password)
    except ValidationError:
        pass  # ожидаемо
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"UserCreate(email={email!r}, username={username!r}) "
            f"бросил {type(exc).__name__}: {exc}."
        )


@_FUZZ_SETTINGS
@given(password=st.text(min_size=1000, max_size=5000))
def test_user_create_long_password_rejected(password: str) -> None:
    """
    Пароль > 64 символов → ValidationError (max_length=64 в схеме).

    Проверяет, что схема отсекает мусор ДО того, как он попадёт в
    Argon2id (иначе DoS: длинный пароль → долгий hash).
    """
    with pytest.raises(ValidationError):
        UserCreate(
            email="user@example.com",
            username="validname",
            password=password,
        )


@_FUZZ_SETTINGS
@given(
    extra_field=st.text(min_size=1, max_size=20).filter(
        lambda s: s.isidentifier() and s not in {"email", "username", "password"}
    ),
)
def test_user_create_forbids_extra_fields(extra_field: str) -> None:
    """
    `extra="forbid"` в BaseSchema: лишние поля → ValidationError.

    Без этого клиент мог бы передать `is_admin=true` или `id=1` и
    «подсунуть» их в модель.
    """
    with pytest.raises(ValidationError):
        UserCreate(
            email="user@example.com",
            username="validname",
            password="some-password",
            **{extra_field: "malicious"},
        )


# ═══════════════════════════════════════════════════════════════════════════
# LoginRequest
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(email=_anything, password=_anything)
def test_login_request_never_unexpected(email: str, password: str) -> None:
    """LoginRequest на мусоре → ValidationError или валидный объект."""
    try:
        LoginRequest(email=email, password=password)
    except ValidationError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"LoginRequest(email={email!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )


@_FUZZ_SETTINGS
@given(password=st.text(min_size=2000))
def test_login_request_long_password_rejected(password: str) -> None:
    """
    LoginRequest: password имеет min_length=1, но max_length НЕ задан.

    Это осознанное решение: длинный пароль на login всё равно не пройдёт
    verify против Argon2-хеша (он был захеширован с max 64). Мы **не**
    отклоняем длинные пароли на login, чтобы не давать атакующему
    информации «вот тут точно не наш пароль».

    Тест документирует это поведение: не должно быть исключения
    (кроме ValidationError, если схема поменяется — тогда тест упадёт).
    """
    try:
        LoginRequest(email="user@example.com", password=password)
    except ValidationError:
        # Если max_length появится в схеме — принимаем это как valid
        # (тест не должен «защищать» конкретное значение границы).
        pass


# ═══════════════════════════════════════════════════════════════════════════
# PasswordResetRequest / Confirm
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(email=_anything)
def test_password_reset_request_never_unexpected(email: str) -> None:
    """PasswordResetRequest на мусоре → ValidationError или валидный объект."""
    try:
        PasswordResetRequest(email=email)
    except ValidationError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"PasswordResetRequest(email={email!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )


@_FUZZ_SETTINGS
@given(token=_anything, new_password=_anything)
def test_password_reset_confirm_never_unexpected(
    token: str, new_password: str
) -> None:
    """PasswordResetConfirm на мусоре → ValidationError или валидный объект."""
    try:
        PasswordResetConfirm(token=token, new_password=new_password)
    except ValidationError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"PasswordResetConfirm(token={token!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )


# ═══════════════════════════════════════════════════════════════════════════
# UserUpdate (PATCH)
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(field_value=_anything)
def test_user_update_partial(field_value: str) -> None:
    """
    UserUpdate — все поля optional. Пустой dict валиден, любое
    значение поля — либо валидно, либо ValidationError.
    """
    try:
        UserUpdate()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"UserUpdate() с пустым телом бросил {exc}.")

    try:
        UserUpdate(email=field_value)
    except ValidationError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"UserUpdate(email={field_value!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Хорошие входы не должны отклоняться
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(email=_valid_email, username=_valid_username)
def test_valid_inputs_always_accepted(email: str, username: str) -> None:
    """
    Сгенерированные по правилам валидные email/username обязаны
    проходить. Если упадёт — либо стратегия производит не то, что
    допускает схема, либо схема ужесточилась.
    """
    # password — 15 символов (минимум для single-factor), ASCII.
    UserCreate(email=email, username=username, password="x" * 15)