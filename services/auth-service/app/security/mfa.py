"""
Утилиты MFA (TOTP): шифрование secret'а, генерация и проверка кодов.

Используется из:
- app/routers/mfa.py — setup / verify / disable
- app/routers/auth.py — /auth/mfa/verify (вторая ступень login)

Replay protection (NIST SP 800-63B Rev 4 §5.1.2):
verify_totp_with_step возвращает номер шага, для которого код совпал.
Вызывающий код обязан проверить, что step > last_used_totp_step,
и обновить last_used_totp_step при успехе.

Явный __all__ — для mypy strict (explicit_package_bases=true):
без него mypy считает, что модуль не экспортирует атрибуты явно,
и падает с attr-defined на импортах вида `from app.security.mfa import X`.
"""

import hashlib
import hmac
import json
import secrets
import time

import pyotp

from app.config import get_settings
from app.security.encryption import EncryptedPayload, get_encryption_service

# ─── AAD (Additional Authenticated Data) ───────────────────────────────────


def _aad(user_id: int) -> str:
    """
    AAD для шифрования MFA-секрета.

    Привязка к пользователю: расшифровка секрета другого пользователя
    провалится, даже если мастер-ключ тот же. В AES-GCM AAD
    участвует в аутентификации; в GOST-CFB игнорируется (нет AEAD),
    но мы всё равно его передаём — для консистентности API.
    """
    return f"mfa:{user_id}"


# ─── Шифрование secret'а ───────────────────────────────────────────────────


def encrypt_secret(secret: str, user_id: int) -> str:
    """
    Зашифровать TOTP-секрет.

    Возвращает JSON-строку `EncryptedPayload.to_dict()` — удобно
    хранить в Text-колонке без парсинга.
    """
    service = get_encryption_service()
    payload = service.encrypt(secret, aad=_aad(user_id))
    return json.dumps(payload.to_dict())


def decrypt_secret(encrypted: str, user_id: int) -> str:
    """Расшифровать TOTP-секрет. AAD должен совпадать с encrypt_secret()."""
    data = json.loads(encrypted)
    payload = EncryptedPayload.from_dict(data)
    service = get_encryption_service()
    return service.decrypt(payload, aad=_aad(user_id)).decode("utf-8")


# ─── TOTP ──────────────────────────────────────────────────────────────────


def _totp_step_now(interval: int) -> int:
    """Номер текущего TOTP-шага (unix_time // interval)."""
    return int(time.time()) // interval


def verify_totp_with_step(secret: str, code: str) -> int | None:
    """
    Проверить TOTP-код и вернуть номер совпавшего шага.

    Возвращает:
    - int  — номер шага (пригодится для replay protection).
    - None — код не подошёл ни для одного шага в окне.

    Окно задаётся settings.mfa_totp_valid_window:
    - 0 — только текущий шаг.
    - 1 — текущий ± 30 сек (рекомендация для компенсации дрейфа часов).

    Почему возвращаем step, а не bool:
    NIST SP 800-63B Rev 4 §5.1.2 требует, чтобы один OTP не принимался
    дважды. Проверка "step > last_used_totp_step" выполняется в
    вызывающем коде, потому что только он знает про конкретный
    MFADevice и его состояние.
    """
    settings = get_settings()
    window = settings.mfa_totp_valid_window

    totp = pyotp.TOTP(secret)
    interval = totp.interval  # по умолчанию 30 секунд
    current_step = _totp_step_now(interval)

    # Проверяем шаги от current-window до current+window.
    # Сравнение constant-time, чтобы не утекал step по таймингу.
    for offset in range(-window, window + 1):
        candidate_step = current_step + offset
        # totp.at(unix_time) возвращает код для step, начинающегося в этот unix_time.
        expected = totp.at(candidate_step * interval)
        if hmac.compare_digest(expected, code):
            return candidate_step

    return None


def generate_totp_code(secret: str) -> str:
    """
    Сгенерировать текущий TOTP-код.

    Нужно только тестам: в проде клиент берёт код у пользователя,
    а не генерирует сам.
    """
    return pyotp.TOTP(secret).now()


# ─── Backup-коды ───────────────────────────────────────────────────────────


def hash_backup_code(code: str) -> str:
    """
    HMAC-SHA256 backup-кода с серверным секретом.

    Не используем Argon2id: backup-коды имеют высокую энтропию
    (~40 бит) и одноразовые — перебор не имеет смысла, а медленный
    хеш дал бы DoS-вектор при переборе в /auth/mfa/verify.
    """
    secret = get_settings().jwt_secret_key.encode()
    return hmac.new(secret, code.encode(), hashlib.sha256).hexdigest()


def generate_backup_codes(count: int) -> tuple[list[str], list[str]]:
    """
    Сгенерировать backup-коды.

    Возвращает (plain_codes, hashes):
    - plain_codes — отдаются клиенту ОДИН РАЗ.
    - hashes — сохраняются в БД (JSON-массив).

    Формат кода: `XXXXX-XXXXX` (10 hex-символов, 40 бит энтропии).
    """
    plain: list[str] = []
    hashes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(5).upper()
        code = f"{raw[:5]}-{raw[5:]}"
        plain.append(code)
        hashes.append(hash_backup_code(code))
    return plain, hashes


def consume_backup_code(
    code: str,
    hashes: list[str],
) -> tuple[bool, list[str]]:
    """
    Проверить backup-код и "съесть" его (удалить из массива).

    Возвращает (matched, remaining_hashes):
    - matched=True — код найден и удалён.
    - matched=False — код не найден, remaining = исходный список.

    Одноразовость: использованный код нельзя применить повторно.
    """
    code_hash = hash_backup_code(code)
    if code_hash in hashes:
        remaining = [h for h in hashes if h != code_hash]
        return True, remaining
    return False, hashes


# ═══════════════════════════════════════════════════════════════════════════
# Explicit exports (для mypy strict)
# ═══════════════════════════════════════════════════════════════════════════
#
# Без явного __all__ mypy в strict-режиме (с explicit_package_bases=true)
# ругается на импорты из этого модуля:
#   "Module app.security.mfa does not explicitly export attribute X"
#
# Публичный API модуля — 7 функций. Приватные (_aad, _totp_step_now)
# не экспортируются.

__all__ = [
    "consume_backup_code",
    "decrypt_secret",
    "encrypt_secret",
    "generate_backup_codes",
    "generate_totp_code",
    "hash_backup_code",
    "verify_totp_with_step",
]
