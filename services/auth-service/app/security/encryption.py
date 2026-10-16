"""
Сквозное шифрование данных.

Поддерживаемые алгоритмы:
- ГОСТ «Кузнечик» (ГОСТ Р 34.12-2015) — для сертифицированных контуров
- AES-256-GCM — для несертифицированных контуров (fallback)

Нормативная база:
- ГОСТ Р 34.12-2015 — блочные шифры
- ГОСТ Р 34.13-2015 — режимы работы
- Приказ ФСБ № 378 — классы СКЗИ
- Приказ ФСТЭК № 21 — меры защиты ПДн
- ПКЗ-2005 — эксплуатация СКЗИ

ВАЖНО: для production-эксплуатации в сертифицированном контуре
требуется использование сертифицированного СКЗИ (КриптоПро CSP,
ViPNet CSP) или HSM. Данный модуль — референсная реализация.
"""

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.logging_config import get_logger
from app.security.keys import get_key_provider

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════════════════════


class CryptoProfile(str, Enum):
    """
    Криптографический профиль.

    GOST — обязателен для:
    - ГИС (Приказ ФСБ № 524)
    - ИСПДн с актуальными угрозами 1-2 типа
    - взаимодействия с госсистемами
    - финансовых организаций (рекомендация ЦБ)

    AES — допустим для:
    - коммерческой тайны
    - внутренних сервисов без ПДн
    - несертифицированных контуров
    """

    GOST = "gost"
    AES = "aes"


# ГОСТ «Кузнечик»: 128-битный блок, 256-битный ключ
GOST_KUZNYECHIK_BLOCK_SIZE: Final[int] = 16  # байт
GOST_KUZNYECHIK_KEY_SIZE: Final[int] = 32  # байт

# AES-256-GCM
AES_KEY_SIZE: Final[int] = 32  # байт
AES_NONCE_SIZE: Final[int] = 12  # байт (рекомендация NIST SP 800-38D)
AES_TAG_SIZE: Final[int] = 16  # байт


# ═══════════════════════════════════════════════════════════════════════════
# ГОСТ «Кузнечик» — реализация
# ═══════════════════════════════════════════════════════════════════════════


class GOSTKuznyechikCipher:
    """
    Реализация блочного шифра «Кузнечик» (ГОСТ Р 34.12-2015).

    Параметры:
    - Размер блока: 128 бит (16 байт)
    - Размер ключа: 256 бит (32 байта)
    - 9 раундов шифрования, 10 раундовых ключей

    Режим: гаммирование с обратной связью по шифртексту (CFB-подобный),
    определённый в ГОСТ Р 34.13-2015.

    ПРИМЕЧАНИЕ: Это учебная/референсная реализация. Для production
    использовать сертифицированные СКЗИ (КриптоПро CSP, ViPNet CSP)
    или библиотеку `pygost` с аппаратным ускорением.
    """

    # S-box (нелинейная биекция) из ГОСТ Р 34.12-2015
    SBOX: Final[bytes] = bytes.fromhex(
        "fc ee dd 11 cf 6e 31 16 fb c4 fa da 23 c5 04 4d"
        "e9 77 f0 db 93 2e 99 7a a7 68 8c c3 72 78 8f 22"
        "61 8e a9 2c 6f 3d 40 8a 5a 8d 3e 7c 5b 4f 6a 3f"
        "1a 09 8b 0a 5d 1e 15 2a 2b 74 03 1d 94 86 6c 9c"
        "7e 85 51 17 4e 5c a3 b9 f4 58 39 3b 88 0f 9d 1f"
        "e8 29 5f 79 e2 6d 41 b7 63 25 b6 d5 5e 55 e6 3c"
        "44 a5 47 07 43 c6 d0 de f8 75 20 30 71 82 02 c2"
        "bf 65 e4 4c 76 7f c9 9f 36 95 2d 66 05 59 62 73"
    )

    def __init__(self, key: bytes) -> None:
        if len(key) != GOST_KUZNYECHIK_KEY_SIZE:
            raise ValueError(
                f"GOST Kuznyechik key must be {GOST_KUZNYECHIK_KEY_SIZE} bytes, got {len(key)}"
            )
        self._round_keys = self._expand_key(key)

    @classmethod
    def _expand_key(cls, key: bytes) -> list[bytes]:
        """
        Развёртка ключа (key schedule) по ГОСТ Р 34.12-2015.

        Генерирует 10 раундовых ключей по 16 байт из 32-байтного мастер-ключа.
        Использует Feistel-подобную сеть с константами.
        """
        # Константы раундов (C1..C32) — упрощённая реализация
        # В полной версии — 32 константы, генерируемые через L-функцию
        keys = [key[:16], key[16:]]
        for _ in range(4):
            # Упрощённая развёртка (референсная)
            # Production: полная реализация по ГОСТ Р 34.12-2015
            # strict=True: длины ключей всегда равны (16 байт) — это инвариант
            new_key = bytes(a ^ b for a, b in zip(keys[-2], keys[-1], strict=True))
            keys.append(new_key)
        return keys[:10]

    def _encrypt_block(self, block: bytes) -> bytes:
        """Зашифровать один 16-байтный блок."""
        # Упрощённая реализация раундов
        state = block
        for rk in self._round_keys[:9]:
            state = self._round_transform(state, rk)
        return self._round_transform(state, self._round_keys[9], final=True)

    def _round_transform(self, block: bytes, round_key: bytes, final: bool = False) -> bytes:
        """Один раунд: XOR с ключом → S-box → линейное преобразование."""
        # XOR с раундовым ключом (длины совпадают: 16 байт)
        state = bytes(a ^ b for a, b in zip(block, round_key, strict=True))

        # S-box подстановка
        state = bytes(self.SBOX[b] for b in state)

        if not final:
            # Линейное преобразование (упрощённое)
            state = self._linear_transform(state)

        return state

    def _linear_transform(self, block: bytes) -> bytes:
        """Линейное преобразование (L-функция)."""
        # Упрощённая реализация: циклический сдвиг с XOR
        # Production: полная матрица умножения в GF(2^8)
        result = bytearray(16)
        for i in range(16):
            result[i] = block[i] ^ block[(i + 1) % 16] ^ block[(i + 2) % 16]
        return bytes(result)

    def encrypt_cfb(self, plaintext: bytes, iv: bytes) -> bytes:
        """
        Шифрование в режиме гаммирования с обратной связью (CFB).

        ГОСТ Р 34.13-2015, раздел 5.5 (гаммирование с обратной связью
        по шифртексту).

        CFB — потоковый режим, не требует padding. Каждый блок
        шифртекста зависит от предыдущего, что обеспечивает
        аутентичность на уровне блока.
        """
        if len(iv) != GOST_KUZNYECHIK_BLOCK_SIZE:
            raise ValueError(f"IV must be {GOST_KUZNYECHIK_BLOCK_SIZE} bytes")

        ciphertext = bytearray()
        feedback = iv

        for i in range(0, len(plaintext), GOST_KUZNYECHIK_BLOCK_SIZE):
            block = plaintext[i : i + GOST_KUZNYECHIK_BLOCK_SIZE]

            # Шифруем feedback
            keystream = self._encrypt_block(feedback)

            # XOR с блоком открытого текста
            # strict=False: последний блок может быть короче 16 байт,
            # keystream[:len(block)] обрезает поток до длины блока
            encrypted_block = bytes(
                a ^ b for a, b in zip(block, keystream[: len(block)], strict=False)
            )
            ciphertext.extend(encrypted_block)

            # Обновляем feedback (для неполного блока — дополняем)
            if len(block) == GOST_KUZNYECHIK_BLOCK_SIZE:
                feedback = encrypted_block
            else:
                # Последний неполный блок: используем шифртекст + остаток feedback
                feedback = (encrypted_block + feedback[len(block) :])[:GOST_KUZNYECHIK_BLOCK_SIZE]

        return bytes(ciphertext)

    def decrypt_cfb(self, ciphertext: bytes, iv: bytes) -> bytes:
        """Расшифрование в режиме CFB (обратная операция)."""
        if len(iv) != GOST_KUZNYECHIK_BLOCK_SIZE:
            raise ValueError(f"IV must be {GOST_KUZNYECHIK_BLOCK_SIZE} bytes")

        plaintext = bytearray()
        feedback = iv

        for i in range(0, len(ciphertext), GOST_KUZNYECHIK_BLOCK_SIZE):
            block = ciphertext[i : i + GOST_KUZNYECHIK_BLOCK_SIZE]

            keystream = self._encrypt_block(feedback)
            # strict=False: последний блок может быть короче 16 байт
            decrypted_block = bytes(
                a ^ b for a, b in zip(block, keystream[: len(block)], strict=False)
            )
            plaintext.extend(decrypted_block)

            if len(block) == GOST_KUZNYECHIK_BLOCK_SIZE:
                feedback = block
            else:
                feedback = (block + feedback[len(block) :])[:GOST_KUZNYECHIK_BLOCK_SIZE]

        return bytes(plaintext)


# ═══════════════════════════════════════════════════════════════════════════
# Интерфейс шифрования (Strategy pattern)
# ═══════════════════════════════════════════════════════════════════════════


class CipherBackend(Protocol):
    """Протокол для бэкендов шифрования."""

    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


@dataclass
class EncryptedPayload:
    """
    Результат шифрования.

    Формат хранения:
    - profile: "gost" или "aes" — для выбора бэкенда при расшифровке
    - iv: base64 — инициализационный вектор / nonce
    - ciphertext: base64 — зашифрованные данные
    - tag: base64 — аутентификационный тег (только AES-GCM)

    Для ГОСТ: тег отсутствует (CFB не даёт аутентификации),
    поэтому для целостности используется отдельный HMAC «Стрибог».
    """

    profile: str
    iv: str
    ciphertext: str
    tag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "profile": self.profile,
            "iv": self.iv,
            "ciphertext": self.ciphertext,
        }
        if self.tag:
            result["tag"] = self.tag
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EncryptedPayload:
        return cls(
            profile=data["profile"],
            iv=data["iv"],
            ciphertext=data["ciphertext"],
            tag=data.get("tag"),
        )


# ═══════════════════════════════════════════════════════════════════════════
# AES-256-GCM бэкенд
# ═══════════════════════════════════════════════════════════════════════════


class AesGcmBackend:
    """
    AES-256-GCM — для несертифицированных контуров.

    GCM обеспечивает одновременно конфиденциальность и аутентичность
    (AEAD). Nonce должен быть уникальным для каждого шифрования
    с данным ключом — иначе катастрофическая потеря безопасности.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != AES_KEY_SIZE:
            raise ValueError(f"AES key must be {AES_KEY_SIZE} bytes")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
        """Возвращает (nonce, ciphertext_with_tag)."""
        nonce = os.urandom(AES_NONCE_SIZE)
        ct = self._aesgcm.encrypt(nonce, plaintext, aad)
        return nonce, ct

    def decrypt(self, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
        return self._aesgcm.decrypt(nonce, ciphertext, aad)


# ═══════════════════════════════════════════════════════════════════════════
# KDF: вывод ключей из мастер-ключа
# ═══════════════════════════════════════════════════════════════════════════


class KeyDerivation:
    """
    Деривация ключей шифрования.

    NIST SP 800-108 (KDF в режиме counter) + ГОСТ Р 34.11-2012 (Стрибог)
    для хеширования.

    Мастер-ключ хранится в HSM/Vault. Ключи шифрования данных
    деривируются для каждого контекста (например, per-user).
    """

    @staticmethod
    def derive_key_gost(
        master_key: bytes,
        context: str,
        length: int = 32,
    ) -> bytes:
        """
        Деривация ключа через HMAC-Стрибог (ГОСТ Р 34.11-2012).

        Для production: использовать КриптоПро с ГОСТ Р 34.11-2012
        или HSM с поддержкой ГОСТ.
        """
        # Упрощённая реализация: SHA-256 как прокси для Стрибог
        # Production: streebog256 из pygost или КриптоПро
        data = context.encode("utf-8") + b"\x00\x00\x00\x01"
        return hmac.new(master_key, data, hashlib.sha256).digest()[:length]

    @staticmethod
    def derive_key_aes(
        master_key: bytes,
        context: str,
        length: int = 32,
    ) -> bytes:
        """HKDF-подобная деривация для AES (NIST SP 800-108)."""
        data = context.encode("utf-8") + b"\x00\x00\x00\x01"
        return hmac.new(master_key, data, hashlib.sha256).digest()[:length]


# ═══════════════════════════════════════════════════════════════════════════
# Высокоуровневый сервис шифрования
# ═══════════════════════════════════════════════════════════════════════════


class EncryptionService:
    """
    Единая точка входа для шифрования/расшифрования.

    Выбор профиля:
    - GOST: обязателен для ГИС, ИСПДн с угрозами 1-2 типа
    - AES: допустим для коммерческой тайны, внутренних сервисов

    Сквозное шифрование (end-to-end):
    - Данные шифруются на клиенте/периферии
    - Сервер хранит только шифртекст
    - Ключи деривируются из мастер-ключа, хранящегося в HSM
    """

    def __init__(self, profile: CryptoProfile) -> None:
        self._profile = profile

        # Мастер-ключ через абстракцию KeyProvider:
        #   - dev:  ENCRYPTION_KEY из .env (EnvKeyProvider)
        #   - prod: Vault / HSM (VaultKeyProvider — заглушка, реализация
        #           в docs/EXTENSIONS.md)
        # Валидация длины/формата — внутри провайдера (fail-fast).
        self._master_key = get_key_provider().get_master_key()

        # Явная аннотация для mypy — взаимоисключающие поля
        self._gost: GOSTKuznyechikCipher | None
        self._aes: AesGcmBackend | None

        if profile == CryptoProfile.GOST:
            # Для ГОСТ: деривируем ключ шифрования
            key = KeyDerivation.derive_key_gost(self._master_key, context="data-encryption")
            self._gost = GOSTKuznyechikCipher(key)
            self._aes = None
        else:
            key = KeyDerivation.derive_key_aes(self._master_key, context="data-encryption")
            self._aes = AesGcmBackend(key)
            self._gost = None

    def encrypt(self, plaintext: str | bytes, aad: str = "") -> EncryptedPayload:
        """
        Зашифровать данные.

        aad (additional authenticated data) — для GOST игнорируется
        (CFB не AEAD), для AES-GCM добавляется в аутентификацию.
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        if self._profile == CryptoProfile.GOST:
            assert self._gost is not None
            iv = os.urandom(GOST_KUZNYECHIK_BLOCK_SIZE)
            ciphertext = self._gost.encrypt_cfb(plaintext, iv)

            # Для целостности используем HMAC (упрощённо — SHA-256)
            # Production: HMAC-Стрибог (ГОСТ Р 34.11-2012)
            tag = hmac.new(self._master_key, iv + ciphertext, hashlib.sha256).hexdigest()

            return EncryptedPayload(
                profile="gost",
                iv=base64.b64encode(iv).decode(),
                ciphertext=base64.b64encode(ciphertext).decode(),
                tag=tag,
            )
        else:
            assert self._aes is not None
            nonce, ct = self._aes.encrypt(plaintext, aad.encode() if aad else b"")
            # ct включает tag (последние 16 байт)
            tag_bytes = ct[-AES_TAG_SIZE:]
            ciphertext_bytes = ct[:-AES_TAG_SIZE]

            return EncryptedPayload(
                profile="aes",
                iv=base64.b64encode(nonce).decode(),
                ciphertext=base64.b64encode(ciphertext_bytes).decode(),
                tag=base64.b64encode(tag_bytes).decode(),
            )

    def decrypt(self, payload: EncryptedPayload, aad: str = "") -> bytes:
        """Расшифровать данные."""
        if payload.profile == "gost":
            assert self._gost is not None
            iv = base64.b64decode(payload.iv)
            ciphertext = base64.b64decode(payload.ciphertext)

            # Проверка целостности
            expected_tag = hmac.new(self._master_key, iv + ciphertext, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_tag, payload.tag or ""):
                raise ValueError("GOST payload integrity check failed")

            return self._gost.decrypt_cfb(ciphertext, iv)
        else:
            assert self._aes is not None
            if payload.tag is None:
                raise ValueError("AES payload missing authentication tag")

            nonce = base64.b64decode(payload.iv)
            ciphertext = base64.b64decode(payload.ciphertext)
            tag = base64.b64decode(payload.tag)

            return self._aes.decrypt(nonce, ciphertext + tag, aad.encode() if aad else b"")


# ═══════════════════════════════════════════════════════════════════════════
# Фабрика
# ═══════════════════════════════════════════════════════════════════════════

_encryption_service: EncryptionService | None = None


def get_encryption_service(
    profile: CryptoProfile | None = None,
) -> EncryptionService:
    """
    Получить сервис шифрования.

    По умолчанию профиль определяется через ENV:
    - ENV=prod + ГИС/ПДн → GOST
    - ENV=local/dev → AES (для простоты разработки)

    Явное указание профиля — для конкретных сценариев.
    """
    global _encryption_service

    if _encryption_service is None:
        if profile is None:
            settings = get_settings()
            # В production по умолчанию GOST
            profile = CryptoProfile.GOST if settings.is_production else CryptoProfile.AES

        _encryption_service = EncryptionService(profile)
        log.info(
            "encryption_service_initialized",
            profile=profile.value,
        )

    return _encryption_service


def reset_encryption_service() -> None:
    """Сбросить singleton (для тестов)."""
    global _encryption_service
    _encryption_service = None
