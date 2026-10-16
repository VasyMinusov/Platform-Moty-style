"""
Роутер аутентификации.

Endpoints:
- POST /auth/register       — регистрация
- POST /auth/login          — вход (1-я ступень; может вернуть mfa_required)
- POST /auth/mfa/verify     — 2-я ступень MFA (обмен mfa_token на пару)
- POST /auth/refresh        — обновление access-токена (rotation)
- POST /auth/logout         — выход (revoke refresh)

NIST SP 800-63B Rev 4:
- Rate limiting на failed attempts (§5.2.2)
- Generic messages для предотвращения enumeration
- Session secrets non-persistent (§7.1)
- Session SHALL NOT extend past AAL timeouts (§7.2)
- MFA-челлендж — отдельный mfa_pending токен (§5.2.2)

Все временные параметры (expire access/refresh) читаются из
app.config.Settings — никакого хардкода.
"""

# ── СТАНДАРТНАЯ БИБЛИОТЕКА ──────────────────────────────────────────────────
import json
from datetime import UTC, datetime
from typing import Any

# ── ТРЕТЬИ СТОРОНЫ ──────────────────────────────────────────────────────────
from fastapi import APIRouter, status
from sqlalchemy import CursorResult, select, update

# ── ЛОКАЛЬНЫЕ ───────────────────────────────────────────────────────────────
from app.audit import write_audit
from app.config import get_settings
from app.dependencies import ClientInfo, CurrentUser, DBSession
from app.exceptions import (
    AccountDisabled,
    AccountLocked,
    AuthenticationFailed,
    InvalidToken,
    PasswordPolicyViolation,
    ResourceConflict,
)
from app.logging_config import get_logger
from app.metrics import (
    auth_lockouts_total,
    auth_logins_total,
    auth_mfa_verifications_total,
    auth_sessions_created_total,
    auth_sessions_revoked_total,
    auth_token_refresh_total,
)
from app.models import (
    AuditAction,
    MFADevice,
    RefreshToken,
    User,
    UserStatus,
)
from app.schemas import (
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    MFALoginVerifyRequest,
    MFAPendingResponse,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
)
from app.security.jwt_handler import TokenType, get_jwt_handler
from app.security.mfa import (
    consume_backup_code,
    decrypt_secret,
    verify_totp_with_step,
)
from app.security.passwords import (
    get_dummy_hash,
    get_password_hasher,
    validate_password,
)
from app.security.rate_limit import get_rate_limiter
from app.services.session import persist_refresh_token

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ═══════════════════════════════════════════════════════════════════════════
# Утилиты
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/register
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация пользователя",
    responses={
        201: {"description": "Пользователь создан"},
        409: {"description": "Email или username занят"},
        422: {"description": "Пароль не соответствует политике"},
    },
)
async def register(
    data: UserCreate,
    db: DBSession,
    client: ClientInfo,
) -> User:
    """
    Регистрация нового пользователя.

    Шаги:
    1. Проверка уникальности email/username.
    2. Валидация пароля по NIST SP 800-63B Rev 4 (async: HIBP check).
    3. Хеширование Argon2id.
    4. Создание User.
    5. Аудит.
    """
    existing = await db.execute(
        select(User).where((User.email == data.email) | (User.username == data.username))
    )
    if existing.scalar_one_or_none():
        raise ResourceConflict("Email or username already registered.")

    validation = await validate_password(
        data.password,
        username=data.username,
        email=data.email,
        is_mfa=False,
    )
    if not validation.is_valid:
        raise PasswordPolicyViolation(errors=validation.errors)

    hasher = get_password_hasher()
    password_hash = hasher.hash(data.password)

    user = User(
        email=data.email,
        username=data.username,
        password_hash=password_hash,
        status=UserStatus.PENDING_VERIFICATION,
        auth_methods="pwd",
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.USER_REGISTERED,
        success=True,
        client=client,
        metadata={"action": "register"},
    )

    log.info("user_registered", user_id=user.id, email=data.email)

    return user


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/login
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/login",
    response_model=TokenResponse | MFAPendingResponse,
    summary="Вход в систему",
    responses={
        200: {
            "description": (
                "Успешный вход: либо TokenResponse (без MFA), "
                "либо MFAPendingResponse (при включённой MFA)"
            ),
        },
        401: {"description": "Неверные credentials (generic)"},
        423: {"description": "Аккаунт заблокирован"},
    },
)
async def login(
    data: LoginRequest,
    db: DBSession,
    client: ClientInfo,
) -> dict[str, object]:
    """
    Вход в систему (1-я ступень).

    Шаги:
    1. Rate limiting check (NIST §5.2.2).
    2. Поиск пользователя.
    3. Timing-safe verify пароля (даже если пользователь не найден).
    4. Проверка статуса.
    5. Если MFA включён — вернуть mfa_pending (БЕЗ access/refresh).
       Иначе — сразу пару access + refresh.
    6. Аудит.

    NIST SP 800-63B Rev 4:
    - SHALL implement rate limiting
    - Generic messages для enumeration
    - Timing attack protection
    - §5.2.2: MFA-челлендж изолирован через mfa_pending токен
    """
    settings = get_settings()
    rate_limiter = get_rate_limiter()
    identifier = data.email.lower()

    # ── 1. Rate limiting ──────────────────────────────────────────────────
    if await rate_limiter.is_locked("login", identifier):
        lockout_remaining = (
            await rate_limiter.get_remaining_lockout("login", identifier) or 60
        )
        auth_logins_total.labels(result="locked").inc()
        auth_lockouts_total.labels(scope="login").inc()
        log.warning("login_rate_limited", identifier=identifier)
        raise AccountLocked(retry_after=lockout_remaining)

    # ── 2. Поиск пользователя ─────────────────────────────────────────────
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # ── 3. Timing-safe verify ─────────────────────────────────────────────
    hasher = get_password_hasher()

    if user is None:
        hasher.verify("dummy", get_dummy_hash())
        await rate_limiter.record_failure("login", identifier)
        auth_logins_total.labels(result="user_not_found").inc()
        await write_audit(
            db,
            user_id=None,
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            client=client,
            metadata={"reason": "user_not_found"},
        )
        # commit: аудит-запись должна сохраниться несмотря на 401.
        await db.commit()
        raise AuthenticationFailed(detail="Invalid email or password.")

    if not hasher.verify(data.password, user.password_hash):
        await rate_limiter.record_failure("login", identifier)

        user.failed_attempts += 1
        user.last_failed_attempt = datetime.now(UTC)

        auth_logins_total.labels(result="invalid_credentials").inc()
        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            client=client,
            metadata={"reason": "invalid_password"},
        )
        # commit: failed_attempts и аудит должны сохраниться.
        await db.commit()
        raise AuthenticationFailed(detail="Invalid email or password.")

    # ── 4. Проверка статуса ───────────────────────────────────────────────
    if user.status == UserStatus.INACTIVE:
        raise AccountDisabled()

    if user.status == UserStatus.LOCKED:
        if user.locked_until is not None and user.locked_until > datetime.now(UTC):
            remaining = int((user.locked_until - datetime.now(UTC)).total_seconds())
            raise AccountLocked(retry_after=remaining)
        user.status = UserStatus.ACTIVE
        user.locked_until = None

    # ── 5. Success: сброс счётчиков ───────────────────────────────────────
    await rate_limiter.record_success("login", identifier)
    user.failed_attempts = 0
    user.last_failed_attempt = None

    if user.status == UserStatus.PENDING_VERIFICATION:
        user.status = UserStatus.ACTIVE

    # ── 6. needs_rehash ───────────────────────────────────────────────────
    if hasher.needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
        log.info("password_rehashed", user_id=user.id)

    # ── 7a. MFA включён → выдаём mfa_pending, НЕ выдаём пару ──────────────
    if user.is_mfa_enabled:
        jwt_handler = get_jwt_handler()
        mfa_token = jwt_handler.create_mfa_pending_token(user.id)

        auth_logins_total.labels(result="mfa_pending").inc()

        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.LOGIN_SUCCESS,
            success=True,
            client=client,
            metadata={"stage": "password_ok", "mfa_required": True},
        )

        log.info("login_mfa_required", user_id=user.id)

        # last_login_at НЕ обновляем — сессия ещё не начата.
        # Обновим после успешного /auth/mfa/verify.
        # auth_sessions_created_total НЕ инкрементим — сессия ещё не создана.
        return {
            "mfa_required": True,
            "mfa_token": mfa_token,
            "expires_in": settings.mfa_temp_token_expire_seconds,
        }

    # ── 7b. MFA выключен → обычный flow ───────────────────────────────────
    user.last_login_at = datetime.now(UTC)

    jwt_handler = get_jwt_handler()
    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        amr=user.get_amr(),
    )
    await persist_refresh_token(db, user_id=user.id, tokens=tokens, client=client)

    # Новая сессия создана (sid новый — create_token_pair без session_id
    # генерирует uuid). Инкрементим счётчик.
    auth_sessions_created_total.inc()
    auth_logins_total.labels(result="success").inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.LOGIN_SUCCESS,
        success=True,
        client=client,
        metadata={"session_id": tokens["session_id"]},
    )

    log.info("login_success", user_id=user.id, session_id=tokens["session_id"])

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "session_id": tokens["session_id"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/mfa/verify — 2-я ступень
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    summary="Вторая ступень MFA (TOTP)",
    responses={
        200: {"description": "Успешный вход: access + refresh"},
        401: {"description": "Invalid mfa_token или неверный код"},
        423: {"description": "Слишком много неверных MFA-кодов — lockout"},
    },
)
async def mfa_login_verify(
    data: MFALoginVerifyRequest,
    db: DBSession,
    client: ClientInfo,
) -> dict[str, object]:
    """
    Обменять mfa_token + TOTP-код на access/refresh.

    Шаги:
    1. Декодировать mfa_token, проверить typ=mfa_pending.
    2. Загрузить user + MFADevice.
    3. Rate limit check (scope="mfa", изолирован от "login").
    4. Расшифровать secret.
    5. Проверить код: сначала TOTP, потом backup (backup — одноразовый).
    6. При успехе — обновить last_login_at, выдать пару.

    NIST SP 800-63B Rev 4 §5.2.2:
    MFA SHALL be verified before session establishment.
    Rate limiting на failed attempts — §5.2.2.
    """
    settings = get_settings()
    jwt_handler = get_jwt_handler()
    rate_limiter = get_rate_limiter()

    # ── 1. Декодируем mfa_token ───────────────────────────────────────────
    try:
        payload = jwt_handler.decode(data.mfa_token, verify=True)
    except Exception as exc:
        log.warning("mfa_token_decode_failed", error=str(exc))
        raise InvalidToken(detail="Invalid MFA token.") from exc

    if payload.get("typ") != TokenType.MFA_PENDING.value:
        raise InvalidToken(detail="Not an MFA-pending token.")

    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise InvalidToken(detail="Invalid mfa_token sub claim.") from exc

    # ── 2. Загружаем user + device ────────────────────────────────────────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    if user is None or not user.is_mfa_enabled:
        raise InvalidToken(detail="User unavailable or MFA not enabled.")

    # ── 3. Rate limit (scope="mfa") ───────────────────────────────────────
    # Scope изолирован от "login": подбор пароля и подбор TOTP — разные
    # атаки, счётчики не должны пересекаться. Identifier — user_id
    # (user известен после декодирования mfa_pending).
    mfa_identifier = str(user_id)
    if await rate_limiter.is_locked("mfa", mfa_identifier):
        lockout_remaining = (
            await rate_limiter.get_remaining_lockout("mfa", mfa_identifier) or 60
        )
        auth_mfa_verifications_total.labels(method="totp", result="locked").inc()
        auth_lockouts_total.labels(scope="mfa").inc()
        log.warning("mfa_rate_limited", user_id=user_id)
        raise AccountLocked(retry_after=lockout_remaining)

    device_result = await db.execute(
        select(MFADevice).where(MFADevice.user_id == user_id)
    )
    device = device_result.scalar_one_or_none()

    if device is None or not device.is_confirmed:
        log.error("mfa_device_missing", user_id=user_id)
        raise InvalidToken(detail="MFA device not configured.")

    # ── 4. Расшифровываем secret ──────────────────────────────────────────
    secret = decrypt_secret(device.secret_encrypted, user.id)

    # ── 5. Проверяем код ──────────────────────────────────────────────────
    # TOTP: replay protection через last_used_totp_step.
    # Backup: одноразовый по природе (consume_backup_code удаляет из массива).
    #
    # NIST SP 800-63B Rev 4 §5.1.2: OTP SHALL NOT быть принят дважды.
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
        log.warning("mfa_login_invalid_code", user_id=user.id)
        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            client=client,
            metadata={"stage": "mfa", "reason": "invalid_code"},
        )
        # commit: аудит и "съеденный" backup-код должны сохраниться
        await db.commit()
        raise AuthenticationFailed(detail="Invalid TOTP or backup code.")

    # ── 6. Успех: сброс rate limiter, обновление состояний ────────────────
    await rate_limiter.record_success("mfa", mfa_identifier)

    device.last_used_at = datetime.now(UTC)
    user.last_login_at = datetime.now(UTC)

    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        amr=user.get_amr(),
    )
    await persist_refresh_token(db, user_id=user.id, tokens=tokens, client=client)

    # Новая сессия (вторая ступень успешно завершена).
    auth_sessions_created_total.inc()

    auth_mfa_verifications_total.labels(
        method="backup" if used_backup else "totp",
        result="success",
    ).inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.LOGIN_SUCCESS,
        success=True,
        client=client,
        metadata={
            "stage": "mfa",
            "session_id": tokens["session_id"],
            "used_backup": used_backup,
        },
    )

    log.info(
        "login_success",
        user_id=user.id,
        session_id=tokens["session_id"],
        mfa_used_backup=used_backup,
    )

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "session_id": tokens["session_id"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access-токена",
    responses={
        200: {"description": "Новая пара токенов"},
        401: {"description": "Refresh-токен невалиден или отозван"},
    },
)
async def refresh(
    data: RefreshRequest,
    db: DBSession,
    client: ClientInfo,
) -> dict[str, object]:
    """
    Обновление access-токена с ротацией refresh.

    NIST SP 800-63B Rev 4 §7.2:
    Session SHALL NOT be extended past AAL timeouts.

    Ротация:
    - Старый refresh помечается used=True.
    - Выдаётся новая пара **в той же сессии** (`session_id` сохраняется).
    - Если старый используется повторно → все сессии пользователя
      инвалидируются (защита от replay-атаки).

    Метрика auth_sessions_created_total НЕ инкрементится: это ротация
    существующей сессии, а не создание новой.
    """
    settings = get_settings()
    jwt_handler = get_jwt_handler()

    # ── 1. Декодируем refresh ─────────────────────────────────────────────
    try:
        payload = jwt_handler.decode(data.refresh_token, verify=True)
    except Exception as exc:
        log.warning("refresh_decode_failed", error=str(exc))
        raise InvalidToken(detail="Invalid refresh token.") from exc

    if payload.get("typ") != "refresh":
        raise InvalidToken(detail="Not a refresh token.")

    jti = payload.get("jti")
    sid = payload.get("sid")
    user_id = int(payload["sub"])

    # ── 2. Ищем токен в БД ────────────────────────────────────────────────
    token_result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    token_row = token_result.scalar_one_or_none()

    if token_row is None:
        log.warning("refresh_token_not_in_db", jti=jti, user_id=user_id)
        auth_token_refresh_total.labels(result="revoked").inc()
        raise InvalidToken(detail="Refresh token revoked.")

    # ── 3. Replay detection ───────────────────────────────────────────────
    if token_row.used:
        auth_token_refresh_total.labels(result="replay").inc()
        log.error(
            "refresh_token_replay_detected",
            jti=jti,
            user_id=user_id,
            session_id=sid,
        )
        revoke_result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,  # noqa: E712
                # Исключаем already-used токены (spent после rotation):
                # они не являются живыми credential'ами, и без этого
                # фильтра UPDATE задевает и сам повторно предъявленный
                # токен (used=True, revoked=False), завышая rowcount
                # и, соответственно, метрику auth_sessions_revoked_total.
                RefreshToken.used == False,  # noqa: E712
            )
            .values(
                revoked=True,
                revoked_at=datetime.now(UTC),
                revoke_reason="replay_detected",
            )
        )
        # rowcount = сколько токенов реально отозвано. Может быть 0,
        # если атакующий повторно предъявил токен после того, как
        # легитимный пользователь уже разлогинился и всё отозвано.
        replay_revoked = (
            revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
        )
        if replay_revoked > 0:
            auth_sessions_revoked_total.labels(
                reason="replay_detected"
            ).inc(replay_revoked)

        # ЯВНЫЙ commit ПЕРЕД raise.
        # NIST SP 800-63B Rev 4 §7.2: при replay — все сессии SHALL be
        # revoked. Без commit get_db() откатит UPDATE на rollback().
        await db.commit()
        raise InvalidToken(detail="Token replay detected. All sessions revoked.")

    if token_row.revoked:
        auth_token_refresh_total.labels(result="revoked").inc()
        raise InvalidToken(detail="Refresh token revoked.")

    if token_row.expires_at < datetime.now(UTC):
        auth_token_refresh_total.labels(result="expired").inc()
        raise InvalidToken(detail="Refresh token expired.")

    # ── 4. Загружаем пользователя ─────────────────────────────────────────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    if user is None or user.status != UserStatus.ACTIVE:
        raise InvalidToken(detail="User unavailable.")

    # ── 5. Rotation: помечаем старый used ─────────────────────────────────
    token_row.used = True
    token_row.last_used_at = datetime.now(UTC)

    # ── 6. Выдаём новую пару в той же сессии ──────────────────────────────
    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        session_id=sid,
        amr=user.get_amr(),
    )

    await persist_refresh_token(db, user_id=user.id, tokens=tokens, client=client)

    auth_token_refresh_total.labels(result="success").inc()

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.TOKEN_REFRESH,
        success=True,
        client=client,
        metadata={"old_jti": jti, "new_jti": tokens["refresh_jti"]},
    )

    log.info("token_refreshed", user_id=user.id, session_id=tokens["session_id"])

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "session_id": tokens["session_id"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/logout
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Выход из системы",
)
async def logout(
    data: LogoutRequest,
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Logout: revoke refresh-токен.

    NIST SP 800-63B Rev 4 §7.1:
    Verifier SHALL terminate the session when requested.
    """
    jwt_handler = get_jwt_handler()

    try:
        payload = jwt_handler.decode(data.refresh_token, verify=True)
    except Exception:
        return MessageResponse(message="Logged out.")

    if int(payload.get("sub", 0)) != user.id:
        log.warning(
            "logout_token_user_mismatch",
            token_sub=payload.get("sub"),
            user_id=user.id,
        )
        return MessageResponse(message="Logged out.")

    jti = payload.get("jti")

    if data.all_sessions:
        revoke_result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked == False,  # noqa: E712
            )
            .values(
                revoked=True,
                revoked_at=datetime.now(UTC),
                revoke_reason="logout_all",
            )
        )
        revoked_count = (
            revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
        )
        if revoked_count > 0:
            auth_sessions_revoked_total.labels(reason="logout_all").inc(revoked_count)
        audit_metadata: dict[str, Any] = {
            "all_sessions": True,
            "count": revoked_count,
        }
    else:
        revoke_result = await db.execute(
            update(RefreshToken)
            .where(RefreshToken.jti == jti)
            .values(
                revoked=True,
                revoked_at=datetime.now(UTC),
                revoke_reason="logout",
            )
        )
        revoked_count = (
            revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
        )
        if revoked_count > 0:
            auth_sessions_revoked_total.labels(reason="logout").inc(revoked_count)
        audit_metadata = {"jti": jti, "count": revoked_count}

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.LOGOUT,
        success=True,
        client=client,
        metadata=audit_metadata,
    )

    log.info("logout_success", user_id=user.id, all_sessions=data.all_sessions)

    return MessageResponse(message="Logged out.")
