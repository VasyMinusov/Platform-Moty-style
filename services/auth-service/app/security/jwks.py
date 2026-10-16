"""
Построение JWK / JWKS из публичного ключа JWT.

JWKS (JSON Web Key Set) — публичный набор ключей для верификации JWT.
Отдаётся по стандартному пути `/.well-known/jwks.json`, чтобы backend'ы
могли валидировать access-токены локально, не зная секрета.

Формат (RFC 7517):
    {
      "keys": [
        {
          "kty": "EC",
          "crv": "P-256",
          "x": "...",     # base64url
          "y": "...",     # base64url
          "use": "sig",
          "alg": "ES256",
          "kid": "..."
        }
      ]
    }

Поддерживаемые алгоритмы:

- **ES256** — полная поддержка (RFC 7518 §6.2.1.2).
  Публичный ключ берётся из `settings.jwt_public_key` или деривируется
  из `settings.jwt_secret_key` (PEM EC private key).

- **HS256** — JWKS возвращает пустой массив. Симметричный секрет
  НЕ публикуется: раздать его через JWKS = скомпрометировать
  безопасность. Клиенты должны валидировать HS256 с общим секретом
  вне JWKS.

- **GOST3410-2012-256/512** — JWKS возвращает пустой массив. RFC 7518
  не стандартизует ГОСТ-ключи в JWK, клиенты должны получать публичный
  ключ вне JWKS (например, через `gostcrypto` вручную).

kid (key ID):
- Если задан `settings.jwt_key_id` — используем его.
- Иначе — RFC 7638 JWK Thumbprint: SHA-256 от канонического JSON
  (required members: crv, kty, x, y для EC), base64url-encoded.
  Стабилен: переживает рестарты, меняется только при смене ключа.

Почему не через jose.jwt:
- python-jose не умеет отдавать JWK из приватного ключа.
- `cryptography` даёт прямой доступ к координатам EC-точки,
  из которых JWK собирается за 5 строк.
"""

import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Base64url helpers (RFC 7515 §2)
# ═══════════════════════════════════════════════════════════════════════════


def _b64url_encode(data: bytes) -> str:
    """base64url без padding — формат для JWK и JWS."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_to_bytes(value: int, length: int = 32) -> bytes:
    """
    Big-endian представление целого фиксированной длины.

    Для P-256 координаты x, y — 32-байтные. Если int влезает в меньшее
    число байт (leading zeros), to_bytes дополнит их нулями.
    """
    return value.to_bytes(length, byteorder="big", signed=False)


# ═══════════════════════════════════════════════════════════════════════════
# PEM → JWK
# ═══════════════════════════════════════════════════════════════════════════


def derive_public_key_pem(private_key_pem: str) -> str:
    """
    Деривировать публичный ключ (PEM) из приватного (PEM).

    Используется, когда `jwt_public_key` не задан явно, но есть
    приватный ключ. Формат: SubjectPublicKeyInfo (стандарт для PEM).
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("ascii"),
        password=None,
    )
    public_key = private_key.public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def pem_to_jwk_es256(public_key_pem: str) -> dict[str, str]:
    """
    PEM → JWK для ES256 (P-256).

    Возвращает JWK без kid — kid добавляется отдельно (см. build_jwks),
    чтобы этот helper был чистым преобразованием PEM → JWK.

    Поднимает ValueError, если кривая не P-256 или ключ не EC.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError(
            f"Expected EC public key, got {type(public_key).__name__}"
        )
    if not isinstance(public_key.curve, ec.SECP256R1):
        raise ValueError(
            f"Expected P-256 curve (secp256r1), got {public_key.curve.name}"
        )

    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(_int_to_bytes(numbers.x, 32)),
        "y": _b64url_encode(_int_to_bytes(numbers.y, 32)),
        "use": "sig",
        "alg": "ES256",
    }


def compute_jwk_thumbprint(jwk: dict[str, str]) -> str:
    """
    RFC 7638 JWK Thumbprint.

    Каноническая форма:
    - Только required members (для EC: crv, kty, x, y).
    - Отсортированы лексикографически.
    - Без пробелов.
    - SHA-256 → base64url.

    Стабильность: при одном и том же ключе thumbprint не меняется
    между рестартами и на разных серверах. Идеально подходит как kid.
    """
    required_members = ["crv", "kty", "x", "y"]
    canonical = {k: jwk[k] for k in required_members if k in jwk}
    canonical_json = json.dumps(
        canonical, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).digest()
    return _b64url_encode(digest)


# ═══════════════════════════════════════════════════════════════════════════
# build_jwks — фасад для роутера
# ═══════════════════════════════════════════════════════════════════════════


def build_jwks() -> dict[str, list[dict[str, str]]]:
    """
    Собрать JWKS для текущего JWT-хендлера.

    Возвращает:
        {"keys": [...]}

    Логика:
    - Эффективный алгоритм берём из `JWTHandler.algorithm` (учитывает
      override в prod — см. `JWTHandler.__init__`).
    - Для ES256 — JWK публичного ключа + kid.
    - Для HS256 / GOST — пустой массив + warning в лог.

    Импорт `jwt_handler` — внутри функции (ленивый) из-за циклической
    зависимости: `jwt_handler` импортирует `jwks` для вычисления kid.
    """
    # Локальный импорт: разрывает цикл jwt_handler ↔ jwks.
    from app.security.jwt_handler import JWTAlgorithm, get_jwt_handler

    handler = get_jwt_handler()
    algorithm = handler.algorithm

    if algorithm == JWTAlgorithm.ES256:
        settings = get_settings()
        try:
            public_pem = settings.jwt_public_key or derive_public_key_pem(
                settings.jwt_secret_key
            )

            jwk = pem_to_jwk_es256(public_pem)

            # kid: явный setting > RFC 7638 thumbprint.
            kid = settings.jwt_key_id or compute_jwk_thumbprint(jwk)
            jwk["kid"] = kid

            return {"keys": [jwk]}

        except Exception as exc:
            log.error("jwks_build_failed", error=str(exc), algorithm=algorithm.value)
            return {"keys": []}

    if algorithm == JWTAlgorithm.HS256:
        log.warning(
            "jwks_empty_symmetric_algorithm",
            algorithm=algorithm.value,
            hint=(
                "JWKS is intended for public keys. For HS256, distribute "
                "the shared secret out-of-band, not via JWKS."
            ),
        )
        return {"keys": []}

    # GOST и прочие — JWK не стандартизует их.
    log.warning(
        "jwks_empty_unsupported_algorithm",
        algorithm=algorithm.value,
        hint=(
            "JWK spec (RFC 7518) does not define GOST key types. "
            "Clients should obtain the public key out-of-band."
        ),
    )
    return {"keys": []}


# ═══════════════════════════════════════════════════════════════════════════
# Explicit exports (для mypy strict)
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "build_jwks",
    "compute_jwk_thumbprint",
    "derive_public_key_pem",
    "pem_to_jwk_es256",
]
