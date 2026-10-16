"""
Роутер управления MFA (TOTP).

Endpoints:
- POST /users/me/mfa/setup    — инициировать настройку, получить secret
- POST /users/me/mfa/verify   — подтвердить владение secret'ом, включить MFA
- POST /users/me/mfa/disable  — отключить MFA (требует TOTP/backup)

NIST SP 800-63B Rev 4:
- §4.2: amr SHALL отражать использованные методы (обновляем auth_methods)
- §5.1.2: OTP SHALL NOT быть принят дважды (replay protection)
- §5.2.2: rate limiting на failed attempts (scope="mfa", изолирован от
  scope="login": подбор пароля и подбор TOTP — разные атаки с разной
  экономикой. TOTP — 10^6 комбинаций, при 5 попытках и lockout 15 мин
  brute-force невозможен).

Все параметры (issuer, TTL, окно TOTP, число backup-кодов) — из Settings.
"""

import json
from datetime import UTC, datetime

import pyotp
from fastapi import APIRouter, status
from sqlalchemy import select

from app.audit import write_audit
from app.config import get_settings
from app.dependencies import ClientInfo, CurrentUser, DBSession
from app.exceptions import (
    AccountLocked,
    AuthenticationFailed,
    ProblemError,
    ResourceConflict,
    ResourceNotFound,
)
from app.logging_config import get_logger
from app.metrics import (
    auth_lockouts_total,
    auth_mfa_setup_total,
    auth_mfa_verifications_total,
)
from app.models import AuditAction, MFADevice
from app.schemas import (
    MessageResponse,
    MFADisableRequest,
    MFASetupResponse,
    MFAVerifySetupRequest,
    MFAVerifySetupResponse,
)
from app.security.mfa import (
    consume_backup_code,
    decrypt_secret,
    encrypt_secret,
    generate_backup_codes,
    verify_totp_with_step,
)
from app.security.rate_limit import get_rate_limiter

log = get_logger(__name__)

router = APIRouter(prefix="/users/me/mfa", tags=["mfa"])


# ═══════════════════════════════════════════════════════════════════════════
# POST /users/me/mfa/setup
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/setup",
    response_model=MFASetupResponse,
    summary="Инициализация MFA (TOTP)",
    responses={
        200: {"description": "Secret сгенерирован"},
        409: {"description": "MFA уже включён"},
    },
)
async def mfa_setup(
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MFASetupResponse:
    """
    Шаг 1 из 2: сгенерировать TOTP-секрет и вернуть его клиенту.

    Flow:
    1. Клиент вызывает этот эндпоинт (уже аутентифицирован).
    2. Сервер генерирует secret, шифрует, сохраняет MFADevice с
       confirmed_at=NULL (MFA ещё НЕ активен).
    3. Клиент показывает пользователю QR (otpauth_url).
    4. Пользователь вводит 6-значный код → POST /verify.

    Повторный /setup до /verify перегенерирует secret.
    После /verify → 409 (сначала disable).
    """
    if user.is_mfa_enabled:
        raise ResourceConflict("MFA is already enabled. Disable it first.")

    # Генерируем secret (base32, 32 байта энтропии — стандарт RFC 6238)
    secret = pyotp.random_base32()
    encrypted = encrypt_secret(secret, user.id)

    # Ищем существующий девайс (незавершённый setup)
    existing_result = await db.execute(
        select(MFADevice).where(MFADevice.user_id == user.id)
    )
    device = existing_result.scalar_one_or_none()

    if device is None:
        device = MFADevice(user_id=user.id, secret_encrypted=encrypted)
        db.add(device)
    else:
        # Перегенерируем: старый secret инвалидируется
        device.secret_encrypted = encrypted
        device.confirmed_at = None
        device.backup_codes_hash = None
        device.last_used_totp_step = None

    auth_mfa_setup_total.labels(result="initiated").inc()
    log.info("mfa_setup_initiated", user_id=user.id)

    settings = get_settings()
    otpauth_url = pyotp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=settings.mfa_totp_issuer,
    )

    return MFASetupResponse(
        secret=secret,
        otpauth_url=otpauth_url,
        issuer=settings.mfa_totp_issuer,
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /users/me/mfa/verify
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/verify",
    response_model=MFAVerifySetupResponse,
    summary="Подтверждение MFA",
    responses={
        200: {"description": "MFA включён, выданы backup-коды"},
        400: {"description": "Setup не инициирован"},
        401: {"description": "Неверный TOTP-код"},
        409: {"description": "MFA уже подтверждён"},
        423: {"description": "Слишком много неверных кодов — lockout"},
    },
)
async def mfa_verify_setup(
    data: MFAVerifySetupRequest,
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MFAVerifySetupResponse:
    """
    Шаг 2 из 2: подтвердить владение secret'ом.

    При успехе:
    - MFADevice.confirmed_at = now
    - MFADevice.last_used_totp_step НЕ сохраняется (см. комментарий ниже)
    - Генерируется N backup-кодов (plaintext — в ответе ОДИН РАЗ)
    - user.is_mfa_enabled = True
    - user.auth_methods = "pwd,otp"

    Rate limiting (scope="mfa"): после 5 неверных кодов — 423.
    """
    device_result = await db.execute(
        select(MFADevice).where(MFADevice.user_id == user.id)
    )
    device = device_result.scalar_one_or_none()

    if device is None:
        raise ProblemError(
            status_code=status.HTTP_400_BAD_REQUEST,
            problem_type="https://api.auth-service.local/problems/mfa-not-initialized",
            title="MFA Not Initialized",
            detail="Call POST /users/me/mfa/setup first.",
        )

    if device.is_confirmed:
        raise ResourceConflict("MFA is already confirmed.")

    # ── Rate limit (scope="mfa") ──────────────────────────────────────────
    rate_limiter = get_rate_limiter()
    mfa_identifier = str(user.id)
    if await rate_limiter.is_locked("mfa", mfa_identifier):
        lockout_remaining = (
            await rate_limiter.get_remaining_lockout("mfa", mfa_identifier) or 60
        )
        auth_lockouts_total.labels(scope="mfa").inc()
        log.warning("mfa_setup_rate_limited", user_id=user.id)
        raise AccountLocked(retry_after=lockout_remaining)

    secret = decrypt_secret(device.secret_encrypted, user.id)

    used_step = verify_totp_with_step(secret, data.code)
    if used_step is None:
        await rate_limiter.record_failure("mfa", mfa_identifier)
        auth_mfa_verifications_total.labels(method="totp", result="invalid").inc()
        log.warning("mfa_setup_invalid_code", user_id=user.id)
        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.MFA_ENABLED,
            success=False,
            client=client,
            metadata={"action": "verify_setup", "reason": "invalid_code"},
        )
        # commit: аудит должен сохраниться, несмотря на 401.
        await db.commit()
        raise AuthenticationFailed(detail="Invalid TOTP code.")

    # Успех — сброс счётчиков rate limiter.
    await rate_limiter.record_success("mfa", mfa_identifier)

    settings = get_settings()
    plain_codes, hashes = generate_backup_codes(settings.mfa_backup_codes_count)

    device.confirmed_at = datetime.now(UTC)
    device.backup_codes_hash = json.dumps(hashes)
    # ВАЖНО: last_used_totp_step здесь НЕ сохраняем.
    #
    # Setup — это enrolment (подтверждение владения secret'ом), а не
    # аутентификация. NIST SP 800-63B Rev 4 §5.1.2 запрещает повторное
    # использование OTP именно при AUTHENTICATION, а не при enrolment.
    #
    # Практическая причина: пользователь, завершивший setup, сразу же
    # логинится в том же 30-секундном окне — с тем же самым кодом.
    # Если мы сохраним step при setup, первый реальный login упадёт с 401
    # (used_step > last_used_totp_step → False).
    #
    # Replay protection включается с первого успешного login/disable —
    # там last_used_totp_step устанавливается и защищает от повторов.

    user.is_mfa_enabled = True
    user.auth_methods = "pwd,otp"

    auth_mfa_setup_total.labels(result="confirmed").inc()
    auth_mfa_verifications_total.labels(method="totp", result="success").inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.MFA_ENABLED,
        success=True,
        client=client,
        metadata={"action": "verify_setup"},
    )

    log.info("mfa_enabled", user_id=user.id)

    return MFAVerifySetupResponse(
        message="MFA enabled. Save backup codes now — they will not be shown again.",
        backup_codes=plain_codes,
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /users/me/mfa/disable
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/disable",
    response_model=MessageResponse,
    summary="Отключение MFA",
    responses={
        200: {"description": "MFA отключён"},
        401: {"description": "Неверный код"},
        404: {"description": "MFA не настроен"},
        423: {"description": "Слишком много неверных кодов — lockout"},
    },
)
async def mfa_disable(
    data: MFADisableRequest,
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Отключить MFA. Требует подтверждения текущим TOTP-кодом ИЛИ
    backup-кодом.

    Defense in depth: угнанная access-сессия не сможет отключить MFA
    без второго фактора.

    NIST SP 800-63B Rev 4 §5.1.2: TOTP-код проверяется на replay
    через last_used_totp_step. Backup-код — одноразовый по своей природе.

    Rate limiting (scope="mfa"): после 5 неверных кодов — 423.
    """
    device_result = await db.execute(
        select(MFADevice).where(MFADevice.user_id == user.id)
    )
    device = device_result.scalar_one_or_none()

    if device is None or not device.is_confirmed:
        raise ResourceNotFound(resource="MFA device")

    # ── Rate limit (scope="mfa") ──────────────────────────────────────────
    rate_limiter = get_rate_limiter()
    mfa_identifier = str(user.id)
    if await rate_limiter.is_locked("mfa", mfa_identifier):
        lockout_remaining = (
            await rate_limiter.get_remaining_lockout("mfa", mfa_identifier) or 60
        )
        auth_lockouts_total.labels(scope="mfa").inc()
        log.warning("mfa_disable_rate_limited", user_id=user.id)
        raise AccountLocked(retry_after=lockout_remaining)

    secret = decrypt_secret(device.secret_encrypted, user.id)

    # Проверяем: TOTP → backup
    code_is_valid = False
    used_backup = False

    used_step = verify_totp_with_step(secret, data.code)
    if used_step is not None and used_step > (device.last_used_totp_step or -1):
        code_is_valid = True
        device.last_used_totp_step = used_step
    elif device.backup_codes_hash:
        hashes: list[str] = json.loads(device.backup_codes_hash)
        matched, remaining_codes = consume_backup_code(data.code, hashes)
        if matched:
            device.backup_codes_hash = json.dumps(remaining_codes)
            code_is_valid = True
            used_backup = True

    if not code_is_valid:
        await rate_limiter.record_failure("mfa", mfa_identifier)
        auth_mfa_verifications_total.labels(method="totp", result="invalid").inc()
        log.warning("mfa_disable_invalid_code", user_id=user.id)
        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.MFA_DISABLED,
            success=False,
            client=client,
            metadata={"action": "disable", "reason": "invalid_code"},
        )
        # commit: аудит должен сохраниться, несмотря на 401.
        await db.commit()
        raise AuthenticationFailed(detail="Invalid TOTP or backup code.")

    # Успех — сброс счётчиков rate limiter.
    await rate_limiter.record_success("mfa", mfa_identifier)

    # Удаляем устройство
    await db.delete(device)
    user.is_mfa_enabled = False
    user.auth_methods = "pwd"

    auth_mfa_setup_total.labels(result="disabled").inc()
    auth_mfa_verifications_total.labels(
        method="backup" if used_backup else "totp",
        result="success",
    ).inc()

    # used_backup различает два способа подтверждения в аудите:
    # - False: пользователь ввёл TOTP-код (у него есть доступ к
    #   аутентификатору).
    # - True: пользователь ввёл backup-код (аутентификатор потерян, либо
    #   backup-код утёк — сигнал для security review).
    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.MFA_DISABLED,
        success=True,
        client=client,
        metadata={"action": "disable", "used_backup": used_backup},
    )

    log.info("mfa_disabled", user_id=user.id, used_backup=used_backup)

    return MessageResponse(message="MFA disabled.")
