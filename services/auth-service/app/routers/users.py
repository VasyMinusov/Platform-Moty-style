"""
Роутер управления профилем и сессиями.

Endpoints:
- GET    /users/me                — текущий профиль
- PATCH  /users/me                — обновление профиля
- POST   /users/me/password       — смена пароля (требует MFA)
- GET    /users/me/sessions       — список активных сессий
- DELETE /users/me/sessions/{sid} — отзыв сессии
- DELETE /users/me/sessions       — отзыв всех сессий

NIST SP 800-63B Rev 4:
- Verifier SHALL terminate session when requested (§7.1)
- Password change: blocklist screening (§5.1.1.2)
- Session SHALL NOT be extended past AAL timeouts (§7.2)
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import CursorResult, or_, select, update

from app.audit import write_audit
from app.dependencies import (
    ClientInfo,
    CurrentUser,
    DBSession,
    MFAUser,
    TokenPayload,
)
from app.exceptions import (
    AuthenticationFailed,
    PasswordPolicyViolation,
    ResourceConflict,
    ResourceNotFound,
)
from app.logging_config import get_logger
from app.metrics import (
    auth_sessions_revoked_total,
)
from app.models import AuditAction, RefreshToken, User
from app.schemas import (
    MessageResponse,
    PasswordChangeRequest,
    SessionRead,
    UserRead,
    UserUpdate,
)
from app.security.passwords import get_password_hasher, validate_password

log = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


# ═══════════════════════════════════════════════════════════════════════════
# GET /users/me
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/me",
    response_model=UserRead,
    summary="Текущий профиль",
)
async def get_me(user: CurrentUser) -> User:
    """
    Получить профиль текущего пользователя.

    Используем `/me`, а не `/{id}` — это защищает от IDOR
    (Insecure Direct Object Reference): пользователь может
    получить только свой профиль, подставить чужой id невозможно.
    """
    return user


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /users/me
# ═══════════════════════════════════════════════════════════════════════════


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Обновление профиля",
)
async def update_me(
    data: UserUpdate,
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> User:
    """
    Частичное обновление профиля.

    Разрешено менять: email, username.
    Запрещено: password (отдельный endpoint), status, is_mfa_enabled
    (требуют отдельного flow).
    """
    update_data = data.model_dump(exclude_unset=True)

    if not update_data:
        return user

    # Проверка уникальности email/username
    if "email" in update_data or "username" in update_data:
        conditions = []
        if "email" in update_data:
            conditions.append(User.email == update_data["email"])
        if "username" in update_data:
            conditions.append(User.username == update_data["username"])

        existing = await db.execute(
            select(User).where(or_(*conditions), User.id != user.id)
        )
        if existing.scalar_one_or_none():
            raise ResourceConflict("Email or username already in use.")

    # Применяем изменения
    for field, value in update_data.items():
        setattr(user, field, value)

    # Если email изменился — сбрасываем верификацию
    if "email" in update_data:
        user.is_email_verified = False

    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.USER_UPDATED,
        success=True,
        client=client,
        metadata={"updated_fields": list(update_data.keys())},
    )

    log.info("user_updated", user_id=user.id, fields=list(update_data.keys()))

    return user


# ═══════════════════════════════════════════════════════════════════════════
# POST /users/me/password
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/me/password",
    response_model=MessageResponse,
    summary="Смена пароля",
    responses={
        200: {"description": "Пароль изменён"},
        401: {"description": "Неверный текущий пароль"},
        403: {"description": "Требуется MFA"},
        422: {"description": "Новый пароль не соответствует политике"},
    },
)
async def change_password(
    data: PasswordChangeRequest,
    user: MFAUser,  # Требует MFA (amr содержит otp/webauthn)
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Смена пароля.

    Требования:
    - MFA-аутентификация (NIST AAL2+). Проверяется по claim `amr`
      текущего access-токена, а не по user.auth_methods (см.
      require_mfa в dependencies.py).
    - Verify текущего пароля (proof of possession).
    - Валидация нового по NIST SP 800-63B Rev 4 (с HIBP).
    - Revoke всех сессий (best practice).

    NIST SP 800-63B Rev 4 §5.1.1.2:
    SHALL compare new passwords against blocklist.
    """
    hasher = get_password_hasher()

    # ── 1. Verify текущего пароля ─────────────────────────────────────────
    if not hasher.verify(data.current_password, user.password_hash):
        await write_audit(
            db,
            user_id=user.id,
            action=AuditAction.PASSWORD_CHANGE,
            success=False,
            client=client,
            metadata={"reason": "invalid_current_password"},
        )
        # commit: аудит должен сохраниться, несмотря на 401.
        await db.commit()
        log.warning("password_change_invalid_current", user_id=user.id)
        raise AuthenticationFailed(detail="Current password is incorrect.")

    # ── 2. Валидация нового пароля (NIST + HIBP) ─────────────────────────
    validation = await validate_password(
        data.new_password,
        username=user.username,
        email=user.email,
        is_mfa=False,  # основной пароль → min 15
    )
    if not validation.is_valid:
        raise PasswordPolicyViolation(errors=validation.errors)

    # ── 3. Проверка, что новый пароль отличается от старого ──────────────
    if hasher.verify(data.new_password, user.password_hash):
        raise PasswordPolicyViolation(
            errors=["New password must be different from the current one."]
        )

    # ── 4. Хешируем и сохраняем ──────────────────────────────────────────
    user.password_hash = hasher.hash(data.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = False  # сбрасываем флаг
    user.failed_attempts = 0
    user.locked_until = None

    # ── 5. Revoke всех сессий ────────────────────────────────────────────
    # Best practice: при смене пароля — разлогинить все устройства.
    # Защита от compromised sessions.
    revoke_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(UTC),
            revoke_reason="password_changed",
        )
    )
    revoked_count = (
        revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
    )
    if revoked_count > 0:
        auth_sessions_revoked_total.labels(reason="password_change").inc(revoked_count)

    # ── 6. Аудит ──────────────────────────────────────────────────────────
    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.PASSWORD_CHANGE,
        success=True,
        client=client,
        metadata={
            "all_sessions_revoked": True,
            "revoked_count": revoked_count,
        },
    )

    log.info("password_changed", user_id=user.id)

    return MessageResponse(
        message="Password changed successfully. Please log in again."
    )


# ═══════════════════════════════════════════════════════════════════════════
# GET /users/me/sessions
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/me/sessions",
    response_model=list[SessionRead],
    summary="Список активных сессий",
)
async def list_sessions(
    user: CurrentUser,
    payload: TokenPayload,
    db: DBSession,
) -> list[SessionRead]:
    """
    Список активных refresh-сессий пользователя.

    Позволяет пользователю видеть, где он залогинен, и отзывать
    подозрительные сессии.

    NIST SP 800-63B Rev 4 §7.1:
    Verifier SHOULD provide a way for the user to view and
    terminate active sessions.

    `is_current` определяется через сравнение `sid` из access-токена
    (claim) с `session_id` каждой сессии в БД. Access-токен живёт
    15 минут, поэтому для длинных сессий возможна погрешность:
    если пользователь обновил access через /refresh, старый access
    в этом запросе уже не используется, и sid — актуальный.
    """
    now = datetime.now(UTC)
    current_sid = payload.get("sid")

    result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.used == False,  # noqa: E712
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.created_at.desc())
    )
    sessions = result.scalars().all()

    return [
        SessionRead(
            session_id=s.session_id,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            is_current=(s.session_id == current_sid),
        )
        for s in sessions
    ]


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /users/me/sessions/{session_id}
# ═══════════════════════════════════════════════════════════════════════════


@router.delete(
    "/me/sessions/{session_id}",
    response_model=MessageResponse,
    summary="Отзыв сессии",
    responses={
        200: {"description": "Сессия отозвана"},
        404: {"description": "Сессия не найдена"},
    },
)
async def revoke_session(
    session_id: str,
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Отозвать конкретную сессию пользователя.

    Проверка ownership: сессия должна принадлежать текущему
    пользователю — иначе 404 (не 403, чтобы не раскрывать
    существование чужих сессий).

    NIST SP 800-63B Rev 4 §7.1:
    Verifier SHALL terminate the session when requested.
    """
    # ── 1. Поиск сессии ───────────────────────────────────────────────────
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.session_id == session_id,
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
            # Исключаем spent-токены после ротации: они уже не
            # действительны (used=True → is_valid=False), а без этого
            # фильтра на одну session_id может быть 2+ строки, и
            # scalar_one_or_none() упадёт с MultipleResultsFound.
            RefreshToken.used == False,  # noqa: E712
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        # Не раскрываем: сессия не существует ИЛИ чужая — одинаковый ответ.
        raise ResourceNotFound(resource="Session")

    # ── 2. Revoke ─────────────────────────────────────────────────────────
    session.revoked = True
    session.revoked_at = datetime.now(UTC)
    session.revoke_reason = "user_revoked"
    auth_sessions_revoked_total.labels(reason="user_revoked").inc()

    # ── 3. Аудит ──────────────────────────────────────────────────────────
    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.TOKEN_REVOKE,
        success=True,
        client=client,
        metadata={"session_id": session_id, "reason": "user_revoked"},
    )

    log.info("session_revoked", user_id=user.id, session_id=session_id)

    return MessageResponse(message="Session revoked.")


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /users/me/sessions
# ═══════════════════════════════════════════════════════════════════════════


@router.delete(
    "/me/sessions",
    response_model=MessageResponse,
    summary="Отзыв всех сессий",
)
async def revoke_all_sessions(
    user: CurrentUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Отозвать все сессии пользователя.

    Полезно при подозрении на компрометацию аккаунта:
    пользователь одним действием разлогинивает все устройства.

    NIST SP 800-63B Rev 4 §7.1:
    Verifier SHALL terminate ALL sessions when requested.
    """
    result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(UTC),
            revoke_reason="user_revoked_all",
        )
    )

    # CursorResult — подкласс Result для DML (UPDATE/DELETE/INSERT),
    # у которого есть .rowcount. Для SELECT .rowcount не определён.
    revoked_count = result.rowcount if isinstance(result, CursorResult) else 0
    if revoked_count > 0:
        auth_sessions_revoked_total.labels(reason="user_revoked_all").inc(revoked_count)

    audit_metadata: dict[str, Any] = {
        "reason": "user_revoked_all",
        "count": revoked_count,
    }
    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.TOKEN_REVOKE,
        success=True,
        client=client,
        metadata=audit_metadata,
    )

    log.info("all_sessions_revoked", user_id=user.id, count=revoked_count)

    return MessageResponse(message=f"All sessions revoked ({revoked_count}).")
