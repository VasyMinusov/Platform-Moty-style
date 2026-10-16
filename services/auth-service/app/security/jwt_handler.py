"""
JWT-хендлер: генерация и валидация токенов.

Поддерживаемые алгоритмы:
- GOST3410-2012-256 / GOST3410-2012-512 (ГОСТ Р 34.10-2012)
- ES256 (ECDSA P-256)
- HS256 (HMAC-SHA256, только для dev)

NIST SP 800-63B Rev 4:
- Session secrets SHALL be non-persistent
- Session continuity SHALL be based on possession of session secret
- Session SHALL NOT be extended past AAL timeouts

ГОСТ Р 34.10-2012:
- ЭЦП на эллиптических кривых
- Хеш: ГОСТ Р 34.11-2012 (Стрибог)

Все временные параметры токенов (issuer, audience, exp) читаются
из app.config.Settings — никакого хардкода.

ВАЖНО про валидацию aud/iss:
python-jose с версии 3.5 сам валидирует claims `aud` и `iss`, если они
присутствуют в токене, и сравнивает с параметрами, переданными в decode().
Мы НЕ передаём audience/issuer в jose (это работало бы только для HS256/ES256,
но не для GOST). Вместо этого валидация aud/iss выполняется в JWTHandler.decode
через self._settings.jwt_audience / jwt_issuer — единообразно для всех бэкендов.

Поэтому в HS256Backend и ES256Backend мы явно отключаем встроенную проверку:
    options={"verify_aud": False, "verify_iss": False}
Иначе jose сравнивает aud с None и кидает JWTClaimsError("Invalid audience").
"""

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Final

from jose import JWTError
from jose import jwt as jose_jwt

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Алгоритмы
# ═══════════════════════════════════════════════════════════════════════════


class JWTAlgorithm(str, Enum):
    """Поддерживаемые алгоритмы подписи JWT."""

    # ГОСТ Р 34.10-2012 (сертифицированный контур)
    GOST_256 = "GOST3410-2012-256"
    GOST_512 = "GOST3410-2012-512"
    # Fallback (несертифицированный контур)
    ES256 = "ES256"
    HS256 = "HS256"  # Только для dev


class TokenType(str, Enum):
    """
    Типы токенов.

    ACCESS / REFRESH — стандартная пара.

    MFA_PENDING — временный токен, выдаваемый после успешной проверки
    пароля, но до прохождения MFA-челленджа. Даёт право только на
    POST /auth/mfa/verify. Не даёт доступа к API.
    """

    ACCESS = "access"
    REFRESH = "refresh"
    MFA_PENDING = "mfa_pending"


# Clock skew (NIST рекомендует leeway для рассинхронизации часов)
CLOCK_SKEW_SECONDS: Final[int] = 30

# Fallback-значения (используются только если Settings недоступны).
# В обычной работе берутся из Settings (jwt_access_token_expire_minutes
# и jwt_refresh_token_expire_days).
_FALLBACK_ACCESS_EXPIRE_MINUTES: Final[int] = 15
_FALLBACK_REFRESH_EXPIRE_DAYS: Final[int] = 7


# ═══════════════════════════════════════════════════════════════════════════
# Claims (RFC 7519 + NIST extensions)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TokenClaims:
    """
    Стандартные claims JWT (RFC 7519).

    Все claims из RFC 7519 + amr (authentication methods references)
    для downstream-сервисов.
    """

    iss: str  # Issuer
    sub: str  # Subject (user_id)
    aud: str  # Audience
    exp: int  # Expiration (Unix timestamp)
    iat: int  # Issued At
    nbf: int  # Not Before
    jti: str  # JWT ID (уникальный, для revocation)
    typ: str  # Token type (access/refresh)
    amr: list[str]  # Authentication methods (NIST)
    sid: str | None = None  # Session ID (для связи access/refresh)


# ═══════════════════════════════════════════════════════════════════════════
# Криптографический бэкенд
# ═══════════════════════════════════════════════════════════════════════════


class JWTCryptoBackend:
    """
    Абстракция над криптографическим бэкендом.

    Реализации:
    - GOSTBackend: ГОСТ Р 34.10-2012 через gostcrypto
    - ES256Backend: ECDSA P-256 через python-jose
    - HS256Backend: HMAC-SHA256 (только dev)

    `headers` — дополнительные поля JWT header (например, `kid`).
    Для HS256/GOST может быть None; для ES256 обычно содержит kid,
    чтобы backend мог выбрать нужный ключ из JWKS.
    """

    def sign(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError

    def verify(self, token: str, key: str) -> dict[str, Any]:
        raise NotImplementedError


class HS256Backend(JWTCryptoBackend):
    """HMAC-SHA256. Только для dev/local."""

    def sign(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> str:
        return jose_jwt.encode(payload, key, algorithm="HS256", headers=headers)

    def verify(self, token: str, key: str) -> dict[str, Any]:
        # verify_aud/verify_iss=False: python-jose с версии 3.5 сам валидирует
        # эти claims, если они есть в токене, и сравнивает с параметрами из
        # decode(). Мы их не передаём (наша валидация — в JWTHandler.decode),
        # поэтому jose сравнил бы aud/iss с None и упал бы с
        # JWTClaimsError("Invalid audience").
        return jose_jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            options={
                "leeway": CLOCK_SKEW_SECONDS,
                "verify_aud": False,
                "verify_iss": False,
            },
        )


class ES256Backend(JWTCryptoBackend):
    """ECDSA P-256. Fallback для несертифицированного контура."""

    def sign(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> str:
        # headers содержит kid — это критично для JWKS:
        # без kid backend не сможет сопоставить токен с ключом.
        return jose_jwt.encode(payload, key, algorithm="ES256", headers=headers)

    def verify(self, token: str, key: str) -> dict[str, Any]:
        # См. комментарий в HS256Backend.verify — та же причина.
        return jose_jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            options={
                "leeway": CLOCK_SKEW_SECONDS,
                "verify_aud": False,
                "verify_iss": False,
            },
        )


class GOSTBackend(JWTCryptoBackend):
    """
    ГОСТ Р 34.10-2012 через gostcrypto.

    Формат подписи: DER-кодированный (r, s).
    Хеш: ГОСТ Р 34.11-2012 (Стрибог).

    ВАЖНО: для production использовать КриптоПро CSP или HSM.
    gostcrypto — референсная реализация для разработки.
    """

    def __init__(self, mode: int = 256) -> None:
        self._mode = mode
        try:
            import gostcrypto.gostsignature as gostsignature

            self._gostsignature = gostsignature
        except ImportError as exc:
            raise RuntimeError(
                "gostcrypto required for GOST JWT. Install: uv add gostcrypto"
            ) from exc

    def _get_curve(self) -> Any:
        """
        Получить параметры эллиптической кривой.

        Используем параметры из RFC 4357 / TC26.
        paramSetB (256-bit) — рекомендованная кривая.
        """
        if self._mode == 256:
            return self._gostsignature.CURVES_R_1323565_1_024_2019[
                "id-tc26-gost-3410-2012-256-paramSetB"
            ]
        return self._gostsignature.CURVES_R_1323565_1_024_2019[
            "id-tc26-gost-3410-12-512-paramSetB"
        ]

    def sign(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        headers: dict[str, Any] | None = None,
    ) -> str:
        """
        Подписать JWT через ГОСТ Р 34.10-2012.

        Реализация:
        1. Формируем JWS Signing Input (header.payload)
        2. Хешируем через Стрибог
        3. Подписываем

        headers может содержать kid (связь с ключом в JWKS).
        """
        # Base64url encode header и payload
        header: dict[str, Any] = {"alg": f"GOST3410-2012-{self._mode}", "typ": "JWT"}
        if headers:
            header.update(headers)
        header_b64 = (
            base64.urlsafe_b64encode(self._json_dumps(header).encode())
            .rstrip(b"=")
            .decode()
        )
        payload_b64 = (
            base64.urlsafe_b64encode(self._json_dumps(payload).encode())
            .rstrip(b"=")
            .decode()
        )

        signing_input = f"{header_b64}.{payload_b64}".encode()

        # Хеш через Стрибог (упрощённо — SHA-256 как прокси)
        # Production: streebog256 из pygost
        digest = hashlib.sha256(signing_input).digest()

        # Подпись
        sign_obj = self._gostsignature.new(
            self._gostsignature.MODE_256, self._get_curve()
        )
        private_key = bytes.fromhex(key)
        signature = sign_obj.sign(private_key, bytearray(digest))

        # Base64url signature
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        return f"{signing_input.decode()}.{sig_b64}"

    def verify(self, token: str, key: str) -> dict[str, Any]:
        """Проверить подпись ГОСТ."""
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError("Invalid JWT format")

        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode()

        digest = hashlib.sha256(signing_input).digest()

        # Декодируем подпись
        signature = base64.urlsafe_b64decode(signature_b64 + "==")

        # Verify
        sign_obj = self._gostsignature.new(
            self._gostsignature.MODE_256, self._get_curve()
        )
        public_key = bytes.fromhex(key)

        if not sign_obj.verify(public_key, bytearray(digest), signature):
            raise JWTError("GOST signature verification failed")

        # Декодируем payload
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==")
        payload: dict[str, Any] = json.loads(payload_json)

        # Проверяем exp/nbf вручную
        now = int(datetime.now(UTC).timestamp())
        if payload.get("exp", 0) < now - CLOCK_SKEW_SECONDS:
            raise JWTError("Token expired")
        if payload.get("nbf", 0) > now + CLOCK_SKEW_SECONDS:
            raise JWTError("Token not yet valid")

        return payload

    @staticmethod
    def _json_dumps(data: dict[str, Any]) -> str:
        return json.dumps(data, separators=(",", ":"), sort_keys=True)


# ═══════════════════════════════════════════════════════════════════════════
# JWT Handler
# ═══════════════════════════════════════════════════════════════════════════


class JWTHandler:
    """
    Высокоуровневый JWT-хендлер.

    Генерирует access + refresh пары, валидирует токены,
    управляет claims по NIST SP 800-63B Rev 4.

    Все временные параметры (issuer, audience, exp) и алгоритм берутся
    из app.config.Settings.
    """

    def __init__(self, algorithm: JWTAlgorithm | None = None) -> None:
        settings = get_settings()
        self._settings = settings

        # Явная аннотация — mypy видит три возможных класса.
        self._backend: JWTCryptoBackend

        # ── Выбор алгоритма ───────────────────────────────────────────────
        if algorithm is None:
            # В prod — GOST, в dev — HS256
            if settings.is_production:
                algorithm = JWTAlgorithm.GOST_256
            else:
                # Пытаемся использовать значение из Settings, если валидно
                try:
                    algorithm = JWTAlgorithm(settings.jwt_algorithm)
                except ValueError:
                    algorithm = JWTAlgorithm.HS256
        self._algorithm = algorithm

        # ── Выбор бэкенда ─────────────────────────────────────────────────
        #
        # kid — идентификатор ключа в JWT header. Заполняется только
        # для асимметричных алгоритмов (ES256): симметричный секрет
        # не привязан к ключу, kid ему не нужен.
        self._key_id: str | None = None

        if algorithm in (JWTAlgorithm.GOST_256, JWTAlgorithm.GOST_512):
            self._backend = GOSTBackend(
                mode=256 if algorithm == JWTAlgorithm.GOST_256 else 512
            )
            self._key = settings.jwt_secret_key  # hex-encoded private key
        elif algorithm == JWTAlgorithm.ES256:
            self._backend = ES256Backend()
            self._key = settings.jwt_secret_key
            self._key_id = self._compute_es256_key_id()
        else:
            self._backend = HS256Backend()
            self._key = settings.jwt_secret_key

        log.info(
            "jwt_handler_initialized",
            algorithm=algorithm.value,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            key_id=self._key_id,
        )

    # ── Внутренние хелперы ────────────────────────────────────────────────

    def _compute_es256_key_id(self) -> str | None:
        """
        Вычислить kid для ES256.

        Приоритет:
        1. settings.jwt_key_id — явное значение.
        2. RFC 7638 JWK Thumbprint публичного ключа.

        Если ни публичный ключ не задан, ни приватный не парсится —
        возвращаем None (токен уйдёт без kid, JWKS останется пустым).
        Это осознанный fallback: сервис продолжит работать, но
        backend'ы не смогут валидировать токены через JWKS.
        """
        settings = self._settings

        if settings.jwt_key_id:
            return settings.jwt_key_id

        try:
            # Ленивый импорт: разрывает цикл jwt_handler ↔ jwks.
            from app.security.jwks import (
                compute_jwk_thumbprint,
                derive_public_key_pem,
                pem_to_jwk_es256,
            )

            public_pem = settings.jwt_public_key or derive_public_key_pem(
                settings.jwt_secret_key
            )

            jwk = pem_to_jwk_es256(public_pem)
            return compute_jwk_thumbprint(jwk)

        except Exception as exc:
            log.warning(
                "jwt_kid_derivation_failed",
                error=str(exc),
                hint=(
                    "JWKS endpoint will return empty keys array. "
                    "Set JWT_PUBLIC_KEY or ensure JWT_SECRET_KEY is "
                    "a valid PEM-encoded EC private key."
                ),
            )
            return None

    def _signing_headers(self) -> dict[str, Any] | None:
        """
        Headers для JWT при подписи.

        Возвращает {"kid": ...} для асимметричных алгоритмов (чтобы
        backend нашёл нужный ключ в JWKS). Для HS256 — None: симметричный
        токен не привязан к публичному ключу.
        """
        if self._key_id:
            return {"kid": self._key_id}
        return None

    def _access_expire_minutes(self) -> int:
        """Взять expire из Settings (fallback на дефолт)."""
        return getattr(
            self._settings,
            "jwt_access_token_expire_minutes",
            _FALLBACK_ACCESS_EXPIRE_MINUTES,
        )

    def _refresh_expire_days(self) -> int:
        """Взять expire из Settings (fallback на дефолт)."""
        return getattr(
            self._settings,
            "jwt_refresh_token_expire_days",
            _FALLBACK_REFRESH_EXPIRE_DAYS,
        )

    # ── Read-only свойства (для JWKS, диагностики) ────────────────────────

    @property
    def algorithm(self) -> JWTAlgorithm:
        """
        Эффективный алгоритм подписи.

        Может отличаться от `settings.jwt_algorithm` — в prod
        `__init__` форсит GOST_256 (см. выше).
        """
        return self._algorithm

    @property
    def key_id(self) -> str | None:
        """
        Key ID для JWT header.

        None для HS256 (нет публичной части) и при невалидном
        приватном ключе для ES256.
        """
        return self._key_id

    # ── Public API ────────────────────────────────────────────────────────

    def create_access_token(
        self,
        user_id: int,
        *,
        session_id: str | None = None,
        amr: list[str] | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> tuple[str, TokenClaims]:
        """
        Создать access-токен.

        Access-токены короткоживущие (15 мин) и stateless.
        NIST: session secret SHALL be non-persistent.
        """
        now = datetime.now(UTC)
        exp = now + timedelta(minutes=self._access_expire_minutes())

        sid = session_id or str(uuid.uuid4())

        claims_dict: dict[str, Any] = {
            "iss": self._settings.jwt_issuer,
            "sub": str(user_id),
            "aud": self._settings.jwt_audience,
            "exp": int(exp.timestamp()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": str(uuid.uuid4()),
            "typ": TokenType.ACCESS.value,
            "amr": amr or ["pwd"],
            "sid": sid,
        }

        if extra_claims:
            claims_dict.update(extra_claims)

        token = self._backend.sign(
            claims_dict, self._key, headers=self._signing_headers()
        )

        claims = TokenClaims(
            iss=claims_dict["iss"],
            sub=claims_dict["sub"],
            aud=claims_dict["aud"],
            exp=claims_dict["exp"],
            iat=claims_dict["iat"],
            nbf=claims_dict["nbf"],
            jti=claims_dict["jti"],
            typ=claims_dict["typ"],
            amr=claims_dict["amr"],
            sid=sid,
        )

        log.info(
            "access_token_created",
            user_id=user_id,
            session_id=sid,
            expires_at=exp.isoformat(),
        )

        return token, claims

    def create_refresh_token(
        self,
        user_id: int,
        *,
        session_id: str,
        amr: list[str] | None = None,
    ) -> tuple[str, TokenClaims]:
        """
        Создать refresh-токен.

        Refresh-токены:
        - Долгоживущие (7 дней, из Settings).
        - Хранятся в БД для revocation.
        - Ротируются при каждом использовании (NIST §7.2).
        """
        now = datetime.now(UTC)
        exp = now + timedelta(days=self._refresh_expire_days())

        claims_dict: dict[str, Any] = {
            "iss": self._settings.jwt_issuer,
            "sub": str(user_id),
            "aud": self._settings.jwt_audience,
            "exp": int(exp.timestamp()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": str(uuid.uuid4()),
            "typ": TokenType.REFRESH.value,
            "amr": amr or ["pwd"],
            "sid": session_id,
        }

        token = self._backend.sign(
            claims_dict, self._key, headers=self._signing_headers()
        )

        claims = TokenClaims(
            iss=claims_dict["iss"],
            sub=claims_dict["sub"],
            aud=claims_dict["aud"],
            exp=claims_dict["exp"],
            iat=claims_dict["iat"],
            nbf=claims_dict["nbf"],
            jti=claims_dict["jti"],
            typ=claims_dict["typ"],
            amr=claims_dict["amr"],
            sid=session_id,
        )

        log.info(
            "refresh_token_created",
            user_id=user_id,
            session_id=session_id,
            jti=claims.jti,
        )

        return token, claims

    def decode(self, token: str, *, verify: bool = True) -> dict[str, Any]:
        """
        Декодировать токен.

        verify=True: полная валидация (подпись, exp, nbf, aud, iss).
        verify=False: только распарсить (для отладки, НЕ для auth).

        Валидация aud/iss выполняется ЗДЕСЬ (не в бэкендах), потому что:
        - работает единообразно для HS256/ES256/GOST
        - jose-бэкенды явно отключают свою встроенную проверку aud/iss
          (см. verify_aud=False, verify_iss=False в HS256Backend/ES256Backend)
        """
        if not verify:
            return jose_jwt.get_unverified_claims(token)

        try:
            payload = self._backend.verify(token, self._key)

            # Проверка aud/iss (NIST рекомендует)
            if payload.get("aud") != self._settings.jwt_audience:
                raise JWTError("Invalid audience")
            if payload.get("iss") != self._settings.jwt_issuer:
                raise JWTError("Invalid issuer")

            return payload

        except JWTError:
            raise
        except Exception as exc:
            log.error("jwt_decode_failed", error=str(exc))
            raise JWTError("Token validation failed") from exc

    def create_mfa_pending_token(self, user_id: int) -> str:
        """
        Создать временный токен для второй ступени аутентификации.

        Тип: `mfa_pending`. Не является access/refresh.
        TTL: settings.mfa_temp_token_expire_seconds (по умолчанию 5 минут).

        Использование:
        1. /auth/login (пароль верный, MFA включён) → mfa_pending token.
        2. /auth/mfa/verify (mfa_pending token + TOTP-код) → access + refresh.

        Зачем отдельный тип, а не access с коротким TTL:
        - typ-claim позволяет /auth/mfa/verify отклонить access/refresh.
        - /users/me и др. endpoints принимают только typ=access —
          mfa_pending нельзя предъявить вместо access.
        - NIST SP 800-63B Rev 4 §5.2.2: вторая ступень аутентификации
          должна иметь изолированный токен/сессию до завершения.
        """
        now = datetime.now(UTC)
        exp = now + timedelta(seconds=self._settings.mfa_temp_token_expire_seconds)

        claims: dict[str, Any] = {
            "iss": self._settings.jwt_issuer,
            "sub": str(user_id),
            "aud": self._settings.jwt_audience,
            "exp": int(exp.timestamp()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": str(uuid.uuid4()),
            "typ": TokenType.MFA_PENDING.value,
        }

        token = self._backend.sign(
            claims, self._key, headers=self._signing_headers()
        )

        log.info(
            "mfa_pending_token_created",
            user_id=user_id,
            expires_at=exp.isoformat(),
        )

        return token

    def create_token_pair(
        self,
        user_id: int,
        *,
        session_id: str | None = None,
        amr: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Создать пару access + refresh токенов.

        `session_id`:
        - None (default) — генерируется новый (используется в login).
        - Задан — сохраняется (используется в refresh, чтобы
          при ротации не терять привязку к сессии: access/refresh
          одной сессии имеют одинаковый `sid`).

        Возвращает dict с токенами и метаданными.
        """
        sid = session_id or str(uuid.uuid4())

        access_token, access_claims = self.create_access_token(
            user_id, session_id=sid, amr=amr
        )
        refresh_token, refresh_claims = self.create_refresh_token(
            user_id, session_id=sid, amr=amr
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self._access_expire_minutes() * 60,
            "session_id": sid,
            "access_jti": access_claims.jti,
            "refresh_jti": refresh_claims.jti,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_jwt_handler: JWTHandler | None = None


def get_jwt_handler() -> JWTHandler:
    global _jwt_handler
    if _jwt_handler is None:
        _jwt_handler = JWTHandler()
    return _jwt_handler


def reset_jwt_handler() -> None:
    """Сбросить singleton (для тестов)."""
    global _jwt_handler
    _jwt_handler = None
