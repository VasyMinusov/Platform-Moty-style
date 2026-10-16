"""
Роутер email-операций: верификация адреса и сброс пароля.

Endpoints:
- POST /auth/verify-email            — запросить письмо (CurrentUser)
- POST /auth/verify-email/confirm    — подтвердить токеном
- POST /auth/password-reset/request  — запросить сброс (public)
- POST /auth/password-reset/confirm  — установить новый пароль

NIST SP 800-63B Rev 4:
- §5.1.1.2: recovery email SHALL be verified before use;
  reset-токен SHALL быть одноразовым и короткоживущим.
- §5.2.2: rate limiting на чувствительные операции.
- Anti-enumeration (OWASP A07:2025): password-reset/request
  всегда возвращает generic 200, даже если email не существует.

Архитектура:
- Одна таблица EmailActionToken для двух сценариев (verify / reset).
- Тип разделяет TTL, шаблоны писем и эндпоинты.
- Токен хранится как HMAC-SHA256-хеш (plaintext — только в письме).
- При успешном confirm инвалидируются все прочие активные токены
  того же типа для этого пользователя: старая ссылка перестаёт
  работать, если пользователь запросил новую.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import CursorResult, select, update

from app.audit import write_audit
from app.config import get_settings
from app.dependencies import (
    ClientInfo,
    CurrentUser,
    DBSession,
    EmailSenderDep,
)
from app.exceptions import (
    InvalidEmailToken,
    PasswordPolicyViolation,
    RateLimitExceeded,
    ResourceConflict,
)
from app.logging_config import get_logger
from app.metrics import (
    auth_email_actions_total,
    auth_sessions_revoked_total,
)
from app.models import (
    AuditAction,
    EmailActionToken,
    EmailActionType,
    RefreshToken,
    User,
    UserStatus,
)
from app.schemas import (
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    VerifyEmailConfirm,
)
from app.security.passwords import get_password_hasher, validate_password
from app.security.rate_limit import get_rate_limiter
from app.security.tokens import (
    build_frontend_url,
    generate_action_token,
    hash_action_token,
)

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ═══════════════════════════════════════════════════════════════════════════
# Внутренние утилиты
# ═══════════════════════════════════════════════════════════════════════════


async def _invalidate_active_tokens(
    db: DBSession,
    *,
    user_id: int,
    action: EmailActionType,
) -> None:
    """
    Пометить used_at=now все активные токены пользователя данного типа.

    Вызывается при создании нового токена или успешном confirm:
    гарантирует, что только один токен каждого типа активен в моменте.
    """
    now = datetime.now(UTC)
    await db.execute(
        update(EmailActionToken)
        .where(
            EmailActionToken.user_id == user_id,
            EmailActionToken.action == action,
            EmailActionToken.used_at.is_(None),
        )
        .values(used_at=now)
    )


async def _create_and_send_token(
    db: DBSession,
    *,
    user: User,
    action: EmailActionType,
    sender: EmailSenderDep,
    client: dict[str, str | None],
) -> None:
    """
    Общая часть для verify-email и password-reset:

    1. Инвалидирует старые активные токены того же типа.
    2. Создаёт новый токен (plaintext — в письме, hash — в БД).
    3. Отправляет письмо с action_url.
    4. Пишет в audit.

    `action_url` формируется из settings.frontend_url + path + token.
    """
    settings = get_settings()

    # 1. Инвалидируем старые — гарантируем единственный активный токен.
    await _invalidate_active_tokens(db, user_id=user.id, action=action)

    # 2. Создаём новый.
    plain_token = generate_action_token()
    token_hash = hash_action_token(plain_token)

    if action == EmailActionType.EMAIL_VERIFICATION:
        ttl_seconds = settings.email_verification_token_ttl_seconds
        frontend_path = "/verify-email"
        subject = f"Подтверждение email — {settings.app_name}"
        text_template = "verify_email.txt"
        html_template = "verify_email.html"
        audit_action = AuditAction.EMAIL_VERIFICATION_SENT
    else:  # PASSWORD_RESET
        ttl_seconds = settings.password_reset_token_ttl_seconds
        frontend_path = "/reset-password"
        subject = f"Сброс пароля — {settings.app_name}"
        text_template = "password_reset.txt"
        html_template = "password_reset.html"
        audit_action = AuditAction.PASSWORD_RESET_REQUESTED

    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

    db.add(
        EmailActionToken(
            user_id=user.id,
            token_hash=token_hash,
            action=action,
            expires_at=expires_at,
            ip_address=client.get("ip_address"),
            user_agent=client.get("user_agent"),
        )
    )
    await db.flush()

    # 3. Собираем URL и отправляем письмо.
    action_url = build_frontend_url(frontend_path, plain_token)

    await sender.send(
        to=user.email,
        subject=subject,
        text_template=text_template,
        html_template=html_template,
        context={
            "action_url": action_url,
            "expires_hours": max(1, ttl_seconds // 3600),
            "service_name": settings.app_name,
        },
    )

    # 4. Audit.
    await write_audit(
        db,
        user_id=user.id,
        action=audit_action,
        success=True,
        client=client,
        metadata={
            "action": action.value,
            "expires_at": expires_at.isoformat(),
        },
    )

    log.info(
        "email_action_sent",
        user_id=user.id,
        action=action.value,
        expires_at=expires_at.isoformat(),
    )


async def _consume_token(
    db: DBSession,
    *,
    raw_token: str,
    expected_action: EmailActionType,
) -> EmailActionToken:
    """
    Найти, проверить и пометить использованным email-токен.

    Возвращает запись EmailActionToken (с user_id).
    Бросает InvalidEmailToken (400) при любой проблеме — generic,
    не раскрываем детали (истёк vs уже использован vs не существует).
    """
    token_hash = hash_action_token(raw_token)

    result = await db.execute(
        select(EmailActionToken).where(EmailActionToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()

    if token_row is None:
        log.warning("email_token_not_found", action=expected_action.value)
        raise InvalidEmailToken()

    if token_row.action != expected_action:
        log.warning(
            "email_token_wrong_action",
            expected=expected_action.value,
            actual=token_row.action.value,
        )
        raise InvalidEmailToken()

    if token_row.used_at is not None:
        log.warning("email_token_already_used", token_id=token_row.id)
        raise InvalidEmailToken()

    if token_row.expires_at < datetime.now(UTC):
        log.warning("email_token_expired", token_id=token_row.id)
        raise InvalidEmailToken()

    token_row.used_at = datetime.now(UTC)
    return token_row


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/verify-email
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Запросить письмо для подтверждения email",
    responses={
        200: {"description": "Письмо отправлено (или уже подтверждён)"},
        409: {"description": "Email уже подтверждён"},
        429: {"description": "Превышен лимит запросов писем"},
    },
)
async def request_email_verification(
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
    email_sender: EmailSenderDep,
) -> MessageResponse:
    """
    Отправить письмо со ссылкой подтверждения.

    Email берётся из auth-контекста (CurrentUser), не из body —
    это защищает от попыток верифицировать чужой адрес.

    Если email уже подтверждён — 409 (нет смысла слать письмо).

    Rate limit: не более N писем в час на пользователя (scope="verify").
    NIST §5.1.1.2 + OWASP A07:2025: защита от email-bombing.
    """
    if user.is_email_verified:
        raise ResourceConflict("Email is already verified.")

    settings = get_settings()
    rate_limiter = get_rate_limiter()

    # ── Quota (scope="verify", identifier=user.id) ────────────────────────
    allowed = await rate_limiter.consume_quota(
        "verify",
        str(user.id),
        limit=settings.rate_limit_email_per_hour,
        window_seconds=3600,
    )
    if not allowed:
        auth_email_actions_total.labels(
            action="verify_email", result="quota_exceeded"
        ).inc()
        log.warning("verify_email_quota_exceeded", user_id=user.id)
        raise RateLimitExceeded(retry_after=3600)

    await _create_and_send_token(
        db,
        user=user,
        action=EmailActionType.EMAIL_VERIFICATION,
        sender=email_sender,
        client=client,
    )

    auth_email_actions_total.labels(action="verify_email", result="sent").inc()

    return MessageResponse(
        message="Verification email sent. Check your inbox."
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/verify-email/confirm
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/verify-email/confirm",
    response_model=MessageResponse,
    summary="Подтвердить email токеном из письма",
    responses={
        200: {"description": "Email подтверждён"},
        400: {"description": "Невалидный или истёкший токен"},
    },
)
async def confirm_email_verification(
    data: VerifyEmailConfirm,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Подтвердить email по токену.

    Публичный endpoint (без auth): токен в письме подписан сервером,
    и пользователь может кликнуть по ссылке до логина.

    При успехе:
    - user.is_email_verified = True
    - Если статус PENDING_VERIFICATION → переходит в ACTIVE
    """
    token_row = await _consume_token(
        db,
        raw_token=data.token,
        expected_action=EmailActionType.EMAIL_VERIFICATION,
    )

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()

    if user is None:
        log.error("email_verify_user_missing", user_id=token_row.user_id)
        raise InvalidEmailToken()

    user.is_email_verified = True
    if user.status == UserStatus.PENDING_VERIFICATION:
        user.status = UserStatus.ACTIVE

    auth_email_actions_total.labels(action="verify_email", result="confirmed").inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.EMAIL_VERIFIED,
        success=True,
        client=client,
        metadata={"action": "verify_email"},
    )

    log.info("email_verified", user_id=user.id)

    return MessageResponse(message="Email verified successfully.")


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/password-reset/request
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Запросить сброс пароля",
    responses={
        200: {"description": "Письмо отправлено (или email не существует — не раскрываем)"},
        429: {"description": "Превышен лимит запросов писем"},
    },
)
async def request_password_reset(
    data: PasswordResetRequest,
    db: DBSession,
    client: ClientInfo,
    email_sender: EmailSenderDep,
) -> MessageResponse:
    """
    Запросить письмо со ссылкой сброса пароля.

    Anti-enumeration (OWASP A07:2025):
    Для несуществующего email возвращает 200 с generic-сообщением.

    Двойной rate limit (scope="reset"):
    1. Hourly quota: не более rate_limit_email_per_hour писем в час
       на email. Превышение → 429 (публичная информация, не зависит
       от существования email).
    2. Min interval: не чаще rate_limit_password_reset_min_interval_seconds
       секунд между двумя письмами. Превышение → 200 generic
       (защита от «10 нажатий подряд → 10 писем»).

    Timing-safe:
    Для несуществующего email — asyncio.sleep(0.05), выравнивающий
    время ответа с существующим email (защита от enumeration
    через тайминги, NIST SP 800-63B Rev 4 §5.1.1.2).
    """
    settings = get_settings()
    rate_limiter = get_rate_limiter()

    # Всегда возвращаем одно и то же сообщение.
    generic_response = MessageResponse(
        message="If the provided email is registered, you will receive reset instructions."
    )

    identifier = data.email.lower()

    # ── 1. Hourly quota ───────────────────────────────────────────────────
    # Проверяем ДО поиска пользователя — чтобы rate limit не зависел
    # от существования email.
    allowed = await rate_limiter.consume_quota(
        "reset",
        identifier,
        limit=settings.rate_limit_email_per_hour,
        window_seconds=3600,
    )
    if not allowed:
        auth_email_actions_total.labels(
            action="password_reset", result="quota_exceeded"
        ).inc()
        log.warning("password_reset_quota_exceeded")
        # 429 — публичная информация (зависит от числа запросов,
        # не от существования email). Anti-enumeration не страдает.
        raise RateLimitExceeded(retry_after=3600)

    # ── 2. Min interval ───────────────────────────────────────────────────
    # Отдельный scope, чтобы не конфликтовать с hourly-квотой.
    # Превышение → 200 generic, письмо не отправляется.
    min_interval = settings.rate_limit_password_reset_min_interval_seconds
    if min_interval > 0:
        allowed_interval = await rate_limiter.consume_quota(
            "reset_interval",
            identifier,
            limit=1,
            window_seconds=min_interval,
        )
        if not allowed_interval:
            auth_email_actions_total.labels(
                action="password_reset", result="interval_throttled"
            ).inc()
            log.info("password_reset_throttled_interval")
            return generic_response

    # ── 3. Поиск пользователя ─────────────────────────────────────────────
    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()

    if user is None:
        # Timing-safe: выравниваем время ответа с существующим email.
        # Без sleep ответ на несуществующий email возвращается на порядок
        # быстрее — атакующий перебором определяет, кто зарегистрирован.
        await asyncio.sleep(0.05)
        log.info("password_reset_requested_unknown_email")
        return generic_response

    if user.status == UserStatus.INACTIVE:
        await asyncio.sleep(0.05)
        log.info("password_reset_requested_inactive", user_id=user.id)
        return generic_response

    await _create_and_send_token(
        db,
        user=user,
        action=EmailActionType.PASSWORD_RESET,
        sender=email_sender,
        client=client,
    )

    auth_email_actions_total.labels(action="password_reset", result="sent").inc()

    return generic_response


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/password-reset/confirm
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    summary="Установить новый пароль по токену",
    responses={
        200: {"description": "Пароль сброшен"},
        400: {"description": "Невалидный или истёкший токен"},
        422: {"description": "Новый пароль не соответствует политике"},
    },
)
async def confirm_password_reset(
    data: PasswordResetConfirm,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Установить новый пароль по токену.

    При успехе:
    - password_hash обновляется
    - Все refresh-сессии отзываются (best practice)
    - Токен помечается used
    """
    token_row = await _consume_token(
        db,
        raw_token=data.token,
        expected_action=EmailActionType.PASSWORD_RESET,
    )

    user_result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = user_result.scalar_one_or_none()

    if user is None:
        log.error("password_reset_user_missing", user_id=token_row.user_id)
        raise InvalidEmailToken()

    # Валидация пароля (NIST + HIBP).
    validation = await validate_password(
        data.new_password,
        username=user.username,
        email=user.email,
        is_mfa=False,
    )
    if not validation.is_valid:
        raise PasswordPolicyViolation(errors=validation.errors)

    # Хешируем и сохраняем.
    hasher = get_password_hasher()
    user.password_hash = hasher.hash(data.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = False
    user.failed_attempts = 0
    user.locked_until = None

    # Revoke всех сессий: после сброса пароля все старые логины
    # должны быть завершены.
    revoke_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(UTC),
            revoke_reason="password_reset",
        )
    )
    revoked_count = (
        revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
    )

    if revoked_count > 0:
        auth_sessions_revoked_total.labels(reason="password_reset").inc(revoked_count)

    auth_email_actions_total.labels(
        action="password_reset", result="confirmed"
    ).inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.PASSWORD_RESET_COMPLETED,
        success=True,
        client=client,
        metadata={
            "action": "reset_password",
            "all_sessions_revoked": True,
            "revoked_count": revoked_count,
        },
    )

    log.info("password_reset_completed", user_id=user.id)

    return MessageResponse(
        message="Password has been reset. Please log in with your new password."
    )
