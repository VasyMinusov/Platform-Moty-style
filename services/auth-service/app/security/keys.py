"""
Абстракция источника мастер-ключа шифрования.

Зачем это нужно:
- В dev мастер-ключ приходит из .env (`ENCRYPTION_KEY`), это удобно.
- В prod секреты должны жить в Vault / HSM и ротироваться, а не
  лежать рядом с кодом в .env.
- Прямая замена `base64.b64decode(settings.encryption_key)` на Vault
  потребовала бы править `EncryptionService.__init__` и все вызовы.
  `KeyProvider(Protocol)` изолирует это решение в одном месте.

Реализации:
- `EnvKeyProvider` — читает `ENCRYPTION_KEY` из .env (текущее поведение).
- `VaultKeyProvider` — заглушка, бросает `NotImplementedError` с
  описанием, как реализовать (см. docs/EXTENSIONS.md).
- HSM — будущее расширение по аналогии с Vault, для сертифицированного
  контура (КриптоПро HSM / ViPNet / Thales).

Как переключать:
    KEY_PROVIDER=env   → EnvKeyProvider (default)
    KEY_PROVIDER=vault → VaultKeyProvider (нужна реализация)

Singleton-обёртка `get_key_provider()` кэширует провайдер на процесс.
`reset_key_provider()` — для тестов и hot-reload.
"""

import base64
from typing import Protocol

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Protocol
# ═══════════════════════════════════════════════════════════════════════════


class KeyProvider(Protocol):
    """
    Источник мастер-ключа шифрования.

    Контракт:
    - `get_master_key()` возвращает ровно 32 байта.
    - Метод может быть дорогим (HTTP к Vault) — вызывающий код должен
      кэшировать результат (или сам провайдер, как EnvKeyProvider).
    - Ошибка на этапе инициализации → fail-fast на startup: невалидный
      конфиг не должен пропускать сервис в рабочее состояние.
    """

    def get_master_key(self) -> bytes:
        """Вернуть 32-байтный мастер-ключ."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# EnvKeyProvider
# ═══════════════════════════════════════════════════════════════════════════


class EnvKeyProvider:
    """
    Читает ENCRYPTION_KEY из .env.

    Формат: base64-строка, декодируется в 32 байта.
    Генерация: `openssl rand -base64 32`.

    Валидация на __init__ — fail-fast, если ключ невалиден:
    - невалидный base64 → ValueError;
    - декодируется не в 32 байта → ValueError.

    Расшифровка в момент конструирования (а не в get_master_key) —
    чтобы ошибки конфига всплывали сразу при создании сервиса, а не
    при первом encrypt/decrypt.
    """

    def __init__(self) -> None:
        settings = get_settings()

        try:
            decoded = base64.b64decode(settings.encryption_key, validate=True)
        except Exception as exc:
            raise ValueError(
                "ENCRYPTION_KEY must be valid base64. "
                "Generate: openssl rand -base64 32"
            ) from exc

        if len(decoded) != 32:
            raise ValueError(
                f"ENCRYPTION_KEY must decode to 32 bytes, got {len(decoded)}. "
                "Generate: openssl rand -base64 32"
            )

        self._key = decoded

    def get_master_key(self) -> bytes:
        """Вернуть закэшированный мастер-ключ."""
        return self._key


# ═══════════════════════════════════════════════════════════════════════════
# VaultKeyProvider (заглушка)
# ═══════════════════════════════════════════════════════════════════════════


class VaultKeyProvider:
    """
    Читает мастер-ключ из HashiCorp Vault.

    ЗАГЛУШКА. Бросает NotImplementedError на __init__, чтобы
    `KEY_PROVIDER=vault` в конфиге упал fail-fast на startup, а не
    молча пропустил сервис в небезопасное состояние.

    Как реализовать — рецепт в `docs/EXTENSIONS.md` → «Vault / HSM
    KeyProvider». Кратко:

    1. `uv add hvac`
    2. `VaultKeyProvider.__init__`:
       - создать `hvac.Client(url=settings.vault_addr,
         token=settings.vault_token)`;
       - проверить `client.is_authenticated()` — fail-fast;
       - прочитать `client.secrets.kv.v2.read_secret_version(path=
         "auth-service")["data"]["data"]["encryption_key"]`;
       - декодировать base64 → 32 байта, сохранить в `self._key`.
    3. `get_master_key()` — вернуть `self._key`.
    4. Ротация: при смене ключа в Vault — перезапуск сервиса
       (или периодический refresh + re-encrypt по расписанию).

    Почему через __init__ (а не lazy get_master_key):
    - Vault-токен проверяется один раз, fail-fast на старте.
    - Не нужно ловить сетевые ошибки в hot path (`encrypt()` каждого
      запроса).
    - Если Vault недоступен — сервис не поднимается. Это правильно:
      без ключа шифрования работать нельзя.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "VaultKeyProvider не реализован. "
            "Рецепт: docs/EXTENSIONS.md → Vault / HSM KeyProvider. "
            "Для использования env-ключа установи KEY_PROVIDER=env."
        )

    def get_master_key(self) -> bytes:
        raise NotImplementedError("VaultKeyProvider not implemented")


# ═══════════════════════════════════════════════════════════════════════════
# Фабрика / singleton
# ═══════════════════════════════════════════════════════════════════════════

_key_provider: KeyProvider | None = None


def get_key_provider() -> KeyProvider:
    """
    Получить провайдер мастер-ключа (singleton на процесс).

    Выбор реализации — через `Settings.key_provider`:
    - "env"   → EnvKeyProvider
    - "vault" → VaultKeyProvider (сейчас NotImplementedError)

    Кэшируется, чтобы HTTP-запрос к Vault не выполнялся на каждый
    encrypt/decrypt.
    """
    global _key_provider

    if _key_provider is None:
        settings = get_settings()
        _key_provider = (
            VaultKeyProvider()
            if settings.key_provider == "vault"
            else EnvKeyProvider()
        )

        log.info("key_provider_initialized", provider=settings.key_provider)

    return _key_provider


def reset_key_provider() -> None:
    """Сбросить singleton (для тестов и hot-reload)."""
    global _key_provider
    _key_provider = None


# ═══════════════════════════════════════════════════════════════════════════
# Explicit exports (для mypy strict)
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "EnvKeyProvider",
    "KeyProvider",
    "VaultKeyProvider",
    "get_key_provider",
    "reset_key_provider",
]
