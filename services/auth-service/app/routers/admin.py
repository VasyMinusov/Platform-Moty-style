"""
Роутер админ-операций.

Endpoints (все требуют AdminUser = MFAUser + is_admin):
- GET    /admin/users/{user_id}                  — просмотр профиля
- POST   /admin/users/{user_id}/unlock           — сброс lockout
- POST   /admin/users/{user_id}/revoke-sessions  — отзыв всех сессий
- GET    /admin/users/{user_id}/audit            — пагинированный audit

NIST SP 800-63B Rev 4 §5.2.2:
Admin-операции требуют AAL2 (MFA) — потому что это high-impact
действия. require_admin строится на MFAUser (см. dependencies.py).

Все изменяющие действия пишутся в audit_logs:
- `user_id` = admin.id (кто сделал);
- `metadata.target_user_id` = victim_id (над кем).

404, не 403 для не-админов: не раскрываем факт существования
admin-эндпоинтов (anti-enumeration). См. require_admin в
dependencies.py.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import CursorResult, func, select, update

from app.audit import write_audit
from app.dependencies import AdminUser, ClientInfo, DBSession
from app.exceptions import ResourceNotFound
from app.logging_config import get_logger
from app.metrics import auth_sessions_revoked_total
from app.models import AuditAction, AuditLog, RefreshToken, User, UserStatus
from app.schemas import (
    AuditLogRead,
    MessageResponse,
    PaginatedResponse,
    UserRead,
)

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════════════════
# Внутренние утилиты
# ═══════════════════════════════════════════════════════════════════════════


async def _load_user_or_404(db: DBSession, user_id: int) -> User:
    """Загрузить User по id или 404."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFound(resource="User")
    return user


# ═══════════════════════════════════════════════════════════════════════════
# GET /admin/users/{user_id}
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Профиль пользователя (admin)",
    responses={
        404: {"description": "Пользователь не найден"},
    },
)
async def get_user(
    user_id: int,
    admin: AdminUser,
    db: DBSession,
) -> User:
    """
    Просмотр профиля произвольного пользователя.

    Возвращает те же поля, что `/users/me` (UserRead), включая
    `is_admin`. Пароль и внутренние счётчики (`failed_attempts`,
    `locked_until`) не раскрываются.

    Не пишет audit — read-only операция, шум в логах не нужен.
    """
    # admin — это зависимость; её присутствие уже гарантирует
    # is_admin + amr проверку.
    _ = admin
    return await _load_user_or_404(db, user_id)


# ═══════════════════════════════════════════════════════════════════════════
# POST /admin/users/{user_id}/unlock
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/users/{user_id}/unlock",
    response_model=MessageResponse,
    summary="Сброс lockout",
    responses={
        404: {"description": "Пользователь не найден"},
    },
)
async def unlock_user(
    user_id: int,
    admin: AdminUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Снять блокировку аккаунта.

    Сбрасывает:
    - `locked_until = NULL`;
    - `failed_attempts = 0`;
    - `last_failed_attempt = NULL`;
    - `status`: LOCKED → ACTIVE.

    Идемпотентен: повторный вызов на незаблокированном пользователе —
    OK, просто пишет ещё одну audit-запись.
    """
    target = await _load_user_or_404(db, user_id)

    target.locked_until = None
    target.failed_attempts = 0
    target.last_failed_attempt = None
    if target.status == UserStatus.LOCKED:
        target.status = UserStatus.ACTIVE

    await write_audit(
        db,
        user_id=admin.id,
        action=AuditAction.ACCOUNT_UNLOCKED,
        success=True,
        client=client,
        metadata={"target_user_id": user_id},
    )

    log.info("admin_unlocked_user", admin_id=admin.id, target_user_id=user_id)

    return MessageResponse(message="User unlocked.")


# ═══════════════════════════════════════════════════════════════════════════
# POST /admin/users/{user_id}/revoke-sessions
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/users/{user_id}/revoke-sessions",
    response_model=MessageResponse,
    summary="Отзыв всех сессий пользователя",
    responses={
        404: {"description": "Пользователь не найден"},
    },
)
async def revoke_user_sessions(
    user_id: int,
    admin: AdminUser,
    db: DBSession,
    client: ClientInfo,
) -> MessageResponse:
    """
    Отозвать все refresh-сессии пользователя.

    Используется при подозрении на компрометацию: администратор
    разлогинивает пользователя на всех устройствах без его участия.

    Идемпотентен: если активных сессий нет, `rowcount=0` — считаем
    успехом, просто пишем в audit с count=0.
    """
    # 404, если пользователь не существует (а не молчаливый 200).
    await _load_user_or_404(db, user_id)

    revoke_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(
            revoked=True,
            revoked_at=datetime.now(UTC),
            revoke_reason="admin_revoked",
        )
    )
    revoked_count = (
        revoke_result.rowcount if isinstance(revoke_result, CursorResult) else 0
    )
    if revoked_count > 0:
        auth_sessions_revoked_total.labels(reason="admin_revoked").inc(revoked_count)

    await write_audit(
        db,
        user_id=admin.id,
        action=AuditAction.TOKEN_REVOKE,
        success=True,
        client=client,
        metadata={
            "target_user_id": user_id,
            "all_sessions": True,
            "count": revoked_count,
            "reason": "admin_revoked",
        },
    )

    log.info(
        "admin_revoked_user_sessions",
        admin_id=admin.id,
        target_user_id=user_id,
        count=revoked_count,
    )

    return MessageResponse(message=f"Revoked {revoked_count} session(s).")


# ═══════════════════════════════════════════════════════════════════════════
# GET /admin/users/{user_id}/audit
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/users/{user_id}/audit",
    response_model=PaginatedResponse[AuditLogRead],
    summary="Аудит-лог пользователя",
    responses={
        404: {"description": "Пользователь не найден"},
    },
)
async def get_user_audit(
    user_id: int,
    admin: AdminUser,
    db: DBSession,
    limit: int = Query(100, ge=1, le=500, description="Page size (1–500)."),
    offset: int = Query(0, ge=0, description="Смещение от начала."),
) -> PaginatedResponse[AuditLogRead]:
    """
    Пагинированный audit-лог пользователя.

    Сортировка: `created_at DESC` (свежие — первыми).

    `limit`/`offset` (не `page`/`per_page`) — стандарт для cursor-less
    пагинации. В ответе `PaginatedResponse` конвертирует их в
    `page`/`per_page` для совместимости с остальным API.

    `total` считается отдельным `SELECT count(*)` — на больших таблицах
    это медленнее, чем курсор, но для admin-эндпоинта (ручной запрос)
    приемлемо. При необходимости — перейти на keyset-пагинацию
    по `(created_at, id)`.
    """
    _ = admin
    # 404, если пользователь не существует.
    await _load_user_or_404(db, user_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.user_id == user_id)
    )
    total = total_result.scalar_one()

    items_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = items_result.scalars().all()

    # Конвертация offset/limit → page/per_page для PaginatedResponse.
    # page = offset // limit + 1, начиная с 1.
    page = (offset // limit) + 1

    return PaginatedResponse[AuditLogRead](
        items=[AuditLogRead.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=limit,
    )
