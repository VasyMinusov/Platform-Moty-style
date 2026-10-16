"""
Fuzz-тесты JWT-хендлера.

Цель: `jwt_handler.decode(malicious, verify=True/False)` не должен
падать с чем-то, кроме `JWTError`. Никаких `AttributeError`,
`ValueError`, `KeyError`, segfault'ов.

Стратегии:

- Случайные Unicode-строки (включая пустые, null bytes, эмодзи).
- JWT-подобные строки (три base64url-сегмента через точку).
- Очень длинные строки (защита от stack overflow в парсере).
- `verify=False` — путь без валидации подписи, там другой код.

Почему тесты async: фикстура `reset_singletons` в conftest — async,
сработает только для async-тестов. Она сбрасывает кеш JWT-хендлера
между примерами (важно, если настройки поменяются).
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jose import JWTError

from app.security.jwt_handler import get_jwt_handler

pytestmark = pytest.mark.fuzz


# Общие настройки: deadline отключаем — первый вызов get_jwt_handler()
# может быть медленным (инициализация), а Hypothesis по умолчанию
# требует, чтобы каждый пример укладывался в 200 мс.
_FUZZ_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ─── Стратегии ─────────────────────────────────────────────────────────────

# Base64url-алфавит, из которого состоит настоящий JWT.
_JWT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

# JWT-подобный сегмент (непустой, реалистичная длина).
_jwt_segment = st.text(alphabet=_JWT_ALPHABET, min_size=1, max_size=500)

# Три сегмента через точку — форма настоящего JWT.
_jwt_like = st.builds(
    lambda a, b, c: f"{a}.{b}.{c}",
    _jwt_segment,
    _jwt_segment,
    _jwt_segment,
)


# ═══════════════════════════════════════════════════════════════════════════
# verify=True
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(raw=st.text(max_size=2000))
async def test_decode_random_text_never_unexpected(raw: str) -> None:
    """
    Любая Unicode-строка на входе `decode(verify=True)` → JWTError
    или валидный payload. Никаких других исключений.
    """
    handler = get_jwt_handler()
    try:
        handler.decode(raw, verify=True)
    except JWTError:
        pass  # ожидаемо
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"decode({raw!r}) бросил {type(exc).__name__}: {exc}. "
            "Ожидалось только JWTError."
        )


@_FUZZ_SETTINGS
@given(token=_jwt_like)
async def test_decode_jwt_shaped_never_unexpected(token: str) -> None:
    """
    JWT-подобная строка (три base64url-сегмента) → JWTError.

    Настоящий JWT без валидной подписи должен падать с JWTError,
    а не с ValueError/KeyError из парсера.
    """
    handler = get_jwt_handler()
    try:
        handler.decode(token, verify=True)
    except JWTError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"decode({token!r}) бросил {type(exc).__name__}: {exc}. "
            "Ожидалось только JWTError."
        )


# ─── Длинные строки ────────────────────────────────────────────────────────
#
# Для тестов с длинными входами используем @pytest.mark.parametrize, а не
# @given. Причины:
#
# 1. Hypothesis не любит стратегии, которые всегда генерируют большие
#    входы. На st.text(min_size=5000, max_size=10000) она падает в
#    FailedHealthCheck (data_too_large, max_allowed_entropy,
#    large_base_example) — уже третья итерация одного и того же конфликта.
#    Suppress'ить каждый health check — это борьба с инструментом.
#
# 2. Цель теста — «парсер не падает на длинном входе», а не «перебрать
#    всё пространство строк такого размера». Достаточно нескольких
#    заранее известных классов входов.
#
# 3. @parametrize документирует, какие именно случаи мы проверяем. Если
#    парсер сломается на новом классе — добавим пример.
#
# Набор примеров покрывает:
#   - чистый ASCII разной длины (5 KB, 10 KB);
#   - строку с null bytes (частая проблема в парсерах);
#   - JWT-подобную строку (три base64url-сегмента) — реалистичный
#     malicious-вход, который должен уйти в JWTError на подписи;
#   - максимальный «мусор» из Unicode (эмодзи и высокие codepoint'ы).
_LONG_STRINGS = [
    "a" * 5000,
    "x" * 10000,
    "\x00" * 5000,
    "a." + "b" * 5000 + ".c",  # JWT-форма: header.payload.signature
    "🔒" * 2500,                # 4-байтовые codepoint'ы, ~10 KB в UTF-8
]


@pytest.mark.parametrize("raw", _LONG_STRINGS)
async def test_decode_very_long_string_never_unexpected(raw: str) -> None:
    """
    Очень длинная строка (5–10 KB) не должна ломать парсер.

    Защита от DoS: атакующий присылает 1 MB строку, приложение
    тратит CPU/память. Здесь проверяем, что на 10 KB нет краша
    (в реальности uvicorn ограничит размер body, но всё равно).

    Используем parametrize, а не @given: цель — покрыть несколько
    конкретных классов длинных входов, а не перебор всех возможных
    строк такого размера. Hypothesis для такого размера не подходит
    (см. комментарий к _LONG_STRINGS).
    """
    handler = get_jwt_handler()
    try:
        handler.decode(raw, verify=True)
    except JWTError:
        pass  # ожидаемо для мусора
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"decode() на строке длиной {len(raw)} бросил "
            f"{type(exc).__name__}: {exc}."
        )


# ═══════════════════════════════════════════════════════════════════════════
# verify=False (unverified path)
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(raw=st.text(max_size=2000))
async def test_decode_unverified_never_unexpected(raw: str) -> None:
    """
    `decode(verify=False)` — путь без валидации подписи.

    Здесь python-jose сразу парсит base64url без проверки подписи:
    мусорные строки дают JWTError, но теоретически может вылететь
    ValueError из base64-декодера. Проверяем, что jwt_handler
    нормализует всё в JWTError.
    """
    handler = get_jwt_handler()
    try:
        handler.decode(raw, verify=False)
    except JWTError:
        pass
    except Exception as exc:  # noqa: BLE001
        # verify=False делегирует прямо в jose.get_unverified_claims,
        # который может бросить JWTError. Другие исключения — баг.
        pytest.fail(
            f"decode(verify=False, {raw!r}) бросил "
            f"{type(exc).__name__}: {exc}."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Граничные значения
# ═══════════════════════════════════════════════════════════════════════════


@_FUZZ_SETTINGS
@given(
    raw=st.one_of(
        st.just(""),
        st.just("."),
        st.just(".."),
        st.just("..."),
        st.just("...."),
        st.just("a.b"),
        st.just("a.b.c.d"),
        st.text(alphabet=".", min_size=1, max_size=20),
    )
)
async def test_decode_dots_only(raw: str) -> None:
    """
    Строки из одних точек и их комбинации — частый malformed-случай.
    """
    handler = get_jwt_handler()
    try:
        handler.decode(raw, verify=True)
    except JWTError:
        pass
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"decode({raw!r}) бросил {type(exc).__name__}: {exc}."
        )