"""
FastAPI-зависимости: аутентификация, авторизация, контекст запроса.

Цепочка зависимостей:
    get_db → get_current_user → require_active_user
                              → require_mfa

Использование в роутерах:
    @router.get("/me")
    async def me(user: CurrentUser):
        return user
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    AccountDisabled,
    AccountLocked,
    AuthenticationFailed,
    InvalidToken,
    MFARequired,
    ResourceNotFound,
)
from app.logging_config import get_logger
from app.models import User, UserStatus
from app.security.jwt_handler import TokenType, get_jwt_handler
from app.services.email_sender import EmailSender, get_email_sender

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Security scheme
# ═══════════════════════════════════════════════════════════════════════════

# HTTPBearer вместо OAuth2PasswordBearer:
# - OAuth2PasswordBearer редиректит на /token при отсутствии токена,
#   что нежелательно для REST API (возвращаем 401, не 302).
# - HTTPBearer сразу возвращает 401/403.
#
bearer_scheme = HTTPBearer(
    scheme_name="Bearer",
    description="JWT access token. Format: `Bearer <token>`",
    auto_error=False,  # Не бросаем 401 автоматически — обрабатываем сами
)


# ═══════════════════════════════════════════════════════════════════════════
# Типизированные аннотации
# ═══════════════════════════════════════════════════════════════════════════

DBSession = Annotated[AsyncSession, Depends(get_db)]
BearerCreds = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


# ═══════════════════════════════════════════════════════════════════════════
# JWT dependency
# ═══════════════════════════════════════════════════════════════════════════


async def get_token_payload(
    credentials: BearerCreds,
) -> dict[str, Any]:
    """
    Извлечь и валидировать JWT payload.

    Возвращает claims (dict) или бросает 401.
    НЕ загружает пользователя из БД — это отдельный шаг.
    """
    if credentials is None:
        raise AuthenticationFailed(detail="Authorization header missing.")

    token = credentials.credentials

    try:
        handler = get_jwt_handler()
        payload = handler.decode(token, verify=True)
    except JWTError as exc:
        log.warning("jwt_validation_failed", error=str(exc))
        raise InvalidToken(detail="Invalid or expired token.") from exc

    # Проверяем тип токена: access (refresh не принимается)
    if payload.get("typ") != TokenType.ACCESS.value:
        log.warning("invalid_token_type", token_type=payload.get("typ"))
        raise InvalidToken(detail="Invalid token type. Access token required.")

    return payload


TokenPayload = Annotated[dict[str, Any], Depends(get_token_payload)]


# ═══════════════════════════════════════════════════════════════════════════
# Current user dependency
# ═══════════════════════════════════════════════════════════════════════════


async def get_current_user(
    db: DBSession,
    payload: TokenPayload,
) -> User:
    """
    Загрузить текущего пользователя из БД по claims.

    Шаги:
    1. Извлечь user_id из `sub`.
    2. Загрузить User из БД.
    3. Проверить, что пользователь существует (не удалён после выдачи токена).
    4. Проверить статус (LOCKED, INACTIVE).
    5. Проверить lockout (NIST rate limiting).

    Sub-dependency: FastAPI вызовет get_db и get_token_payload
    автоматически.
    """
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise InvalidToken(detail="Token missing 'sub' claim.")

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError) as exc:
        raise InvalidToken(detail="Invalid 'sub' claim format.") from exc

    # Загружаем пользователя
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Пользователь удалён, но токен ещё валиден.
        # NIST SP 800-63B Rev 4: SHALL verify user still exists.
        log.warning("user_not_found_for_token", user_id=user_id)
        raise InvalidToken(detail="User no longer exists.")

    # ── Проверка статуса ──────────────────────────────────────────────────
    if user.status == UserStatus.INACTIVE:
        log.warning("inactive_user_access", user_id=user_id)
        raise AccountDisabled()

    if user.status == UserStatus.LOCKED:
        # Проверяем, истёк ли lockout
        if user.locked_until is not None and user.locked_until > datetime.now(UTC):
            remaining = int((user.locked_until - datetime.now(UTC)).total_seconds())
            raise AccountLocked(retry_after=remaining)

        # Lockout истёк — разблокируем (lazy unlock)
        user.status = UserStatus.ACTIVE
        user.locked_until = None
        user.failed_attempts = 0
        await db.flush()

    # ── Проверка rate limiting ────────────────────────────────────────────
    # NIST SP 800-63B Rev 4 §5.2.2: rate limiting на failed attempts
    if user.is_locked and user.locked_until is not None:
        remaining = int((user.locked_until - datetime.now(UTC)).total_seconds())
        raise AccountLocked(retry_after=remaining)

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ═══════════════════════════════════════════════════════════════════════════
# Optional current user (для public endpoints)
# ═══════════════════════════════════════════════════════════════════════════


async def get_current_user_optional(
    db: DBSession,
    credentials: BearerCreds,
) -> User | None:
    """
    Вернуть пользователя, если токен валиден, иначе None.

    Использование: endpoints, работающие и с auth, и без.
    Например, лента новостей: авторизованные видят персонализированное,
    анонимные — общее.
    """
    if credentials is None:
        return None

    try:
        handler = get_jwt_handler()
        payload = handler.decode(credentials.credentials, verify=True)
    except JWTError:
        return None

    if payload.get("typ") != TokenType.ACCESS.value:
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or user.status != UserStatus.ACTIVE:
        return None

    return user


OptionalCurrentUser = Annotated[User | None, Depends(get_current_user_optional)]


# ═══════════════════════════════════════════════════════════════════════════
# MFA requirement
# ═══════════════════════════════════════════════════════════════════════════


async def require_mfa(user: CurrentUser, payload: TokenPayload) -> User:
    """
    Требовать MFA-аутентификацию.

    Проверяет claim `amr` (authentication methods references) в
    ТЕКУЩЕМ access-токене, а не в БД.

    Почему не из БД (user.get_amr()):
    Если пользователь включил MFA в сессии A, но в сессии B прошёл
    только по паролю — доступ к критичным операциям в сессии B должен
    быть заблокирован. `user.auth_methods` в БД показывает, какие
    методы НАСТРОЕНЫ у пользователя, но не какие ИСПОЛЬЗОВАНЫ в текущей
    сессии. Источник правды для проверки AAL — claim `amr` в токене.

    NIST SP 800-63B Rev 4 §4.2: amr SHALL отражать методы, использованные
    при аутентификации, для downstream-сервисов.

    Использование:
        @router.post("/admin", dependencies=[Depends(require_mfa)])
    """
    amr = payload.get("amr", [])

    if "otp" not in amr and "webauthn" not in amr:
        log.warning("mfa_required_but_not_present", user_id=user.id, amr=amr)
        raise MFARequired()

    return user


MFAUser = Annotated[User, Depends(require_mfa)]


# ═══════════════════════════════════════════════════════════════════════════
# Admin requirement
# ═══════════════════════════════════════════════════════════════════════════


async def require_admin(user: CurrentUser, payload: TokenPayload) -> User:
    """
    Требовать роль администратора + MFA.

    Порядок проверок ВАЖЕН для anti-enumeration:

    1. **Сначала `is_admin`.** Если False → 404 (не 403). Не-админ
       не должен даже косвенно узнать, что такой эндпоинт существует.
       Если бы мы отвечали 403 `mfa-required`, обычный пользователь
       без MFA догадался бы, что «здесь что-то есть, но нужен второй
       фактор».

    2. **Потом MFA.** Админ, но amr без otp/webauthn → 403
       `mfa-required`. Это уже осмысленный ответ: пользователь знает
       про эндпоинт (он админ), но должен пройти MFA.

    Почему НЕ строим поверх MFAUser:
    FastAPI разрешает зависимости снизу вверх. `require_admin(user: MFAUser)`
    вызовет `require_mfa` ДО проверки `is_admin`, и обычный пользователь
    без MFA получит 403 вместо 404 — утечка факта существования
    эндпоинта. Именно этот баг ловил test_non_admin_gets_404.

    Проверка MFA — по claim `amr` текущего access-токена (как в
    require_mfa), а не по `user.is_mfa_enabled`: если админ включил
    MFA в сессии A, но в сессии B прошёл только по паролю, admin-эндпоинты
    в B должны быть недоступны.
    """
    # ── 1. Роль ───────────────────────────────────────────────────────────
    if not user.is_admin:
        log.warning(
            "admin_access_denied",
            user_id=user.id,
        )
        raise ResourceNotFound(resource="Admin endpoint")

    # ── 2. MFA ────────────────────────────────────────────────────────────
    amr = payload.get("amr", [])
    if "otp" not in amr and "webauthn" not in amr:
        log.warning("admin_mfa_required", user_id=user.id, amr=amr)
        raise MFARequired()

    return user


AdminUser = Annotated[User, Depends(require_admin)]


# ═══════════════════════════════════════════════════════════════════════════
# Client info (IP, User-Agent)
# ═══════════════════════════════════════════════════════════════════════════


async def get_client_info(request: Request) -> dict[str, str | None]:
    """
    Извлечь информацию о клиенте для аудита.

    IP-адрес:
    - `request.client.host` — proxy-aware при `--proxy-headers`.
    - Uvicorn по умолчанию доверяет `X-Forwarded-For` только с
      `forwarded-allow-ips`.

    User-Agent:
    - Может быть None (некоторые клиенты не отправляют).
    - Ограничиваем 512 символами (защита от переполнения).
    """
    client_host = None
    if request.client:
        client_host = request.client.host

    user_agent = request.headers.get("user-agent")
    if user_agent and len(user_agent) > 512:
        user_agent = user_agent[:512]

    return {
        "ip_address": client_host,
        "user_agent": user_agent,
    }


ClientInfo = Annotated[dict[str, str | None], Depends(get_client_info)]


# ═══════════════════════════════════════════════════════════════════════════
# Email sender (для писем верификации / сброса пароля)
# ═══════════════════════════════════════════════════════════════════════════

# В проде — SmtpEmailSender (singleton). В тестах — MockEmailSender,
# подменяется через app.dependency_overrides[get_email_sender] в conftest.py.
#
# Используем Annotated вместо `email_sender: EmailSender = Depends(...)`:
#  - Ruff B008 (function-call-in-default-argument) молчит.
#  - mypy strict корректно выводит тип (без Annotated он видит
#    `Depends` как дефолт и теряет EmailSender).
#  - Консистентно с DBSession / CurrentUser / ClientInfo.
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
