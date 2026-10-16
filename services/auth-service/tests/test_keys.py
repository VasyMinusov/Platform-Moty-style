"""
Тесты KeyProvider — источника мастер-ключа.

Покрытие:
- EnvKeyProvider корректно декодирует base64 и валидирует длину.
- Невалидный base64 → ValueError.
- Неверная длина → ValueError.
- get_key_provider() возвращает EnvKeyProvider по умолчанию.
- get_key_provider() — singleton.
- KEY_PROVIDER=vault → NotImplementedError на этапе конструирования.

Фикстура reset_singletons (autouse в conftest) сбрасывает
_key_provider между тестами.
"""

import base64

import pytest

from app.config import get_settings
from app.security.keys import (
    EnvKeyProvider,
    VaultKeyProvider,
    get_key_provider,
    reset_key_provider,
)


# ═══════════════════════════════════════════════════════════════════════════
# EnvKeyProvider
# ═══════════════════════════════════════════════════════════════════════════


def test_env_key_provider_returns_32_bytes() -> None:
    """get_master_key() возвращает ровно 32 байта."""
    provider = EnvKeyProvider()
    key = provider.get_master_key()

    assert isinstance(key, bytes)
    assert len(key) == 32


def test_env_key_provider_decodes_base64() -> None:
    """
    Проверяем, что ключ действительно декодируется из base64.

    conftest.py устанавливает ENCRYPTION_KEY=base64(b"test-encryption-key-32-bytes-len"),
    что декодируется ровно в 32 байта — минимальное требование
    EnvKeyProvider (иначе ValueError).
    """
    provider = EnvKeyProvider()
    key = provider.get_master_key()

    assert key == b"test-encryption-key-32-bytes-len"
    assert len(key) == 32


def test_env_key_provider_rejects_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Невалидный base64 → ValueError с понятным сообщением."""
    # Подменяем настройки — «not-base64!!!» содержит символы, которых нет
    # в base64-алфавите, validate=True в b64decode их отвергнет.
    get_settings.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", "not-base64!!!")
    reset_key_provider()

    with pytest.raises(ValueError, match="base64"):
        EnvKeyProvider()


def test_env_key_provider_rejects_wrong_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """base64 от 16 байт → ValueError про длину (нужно 32)."""
    short_key = base64.b64encode(b"x" * 16).decode()
    get_settings.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", short_key)
    reset_key_provider()

    with pytest.raises(ValueError, match="32 bytes"):
        EnvKeyProvider()


# ═══════════════════════════════════════════════════════════════════════════
# get_key_provider — фабрика / singleton
# ═══════════════════════════════════════════════════════════════════════════


def test_get_key_provider_returns_env_by_default() -> None:
    """Без KEY_PROVIDER в env — используется EnvKeyProvider."""
    reset_key_provider()
    provider = get_key_provider()

    assert isinstance(provider, EnvKeyProvider)


def test_get_key_provider_is_singleton() -> None:
    """Повторный вызов возвращает тот же инстанс."""
    reset_key_provider()
    a = get_key_provider()
    b = get_key_provider()

    assert a is b


def test_get_key_provider_vault_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    KEY_PROVIDER=vault → NotImplementedError с подсказкой.

    Fail-fast: невалидный конфиг должен упасть на старте, а не
    молча пропустить сервис в небезопасное состояние.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("KEY_PROVIDER", "vault")
    reset_key_provider()

    with pytest.raises(NotImplementedError, match="VaultKeyProvider"):
        get_key_provider()


# ═══════════════════════════════════════════════════════════════════════════
# VaultKeyProvider — заглушка
# ═══════════════════════════════════════════════════════════════════════════


def test_vault_key_provider_direct_instantiation_raises() -> None:
    """Прямое конструирование тоже падает с понятным сообщением."""
    with pytest.raises(NotImplementedError, match="docs/EXTENSIONS.md"):
        VaultKeyProvider()