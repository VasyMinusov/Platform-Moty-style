from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserRole
from ..schemas import UserOut, AdminUserUpdate, RoleUpdate
from ..security import require_admin, require_moderator
from ..services import challenge_registry, orchestrator

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/challenges/sync")
def sync_challenges(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Пересканировать CHALLENGES_DIR и синхронизировать БД.
    Вызывайте после добавления новой папки-задания — код менять не нужно."""
    count = challenge_registry.sync_challenges(db)
    return {"synced": count}


@router.post("/instances/reap")
def reap_expired(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Ручной запуск очистки просроченных контейнеров
    (в проде лучше вызывать по расписанию, например APScheduler)."""
    count = orchestrator.reap_expired(db)
    return {"stopped": count}


# ── Управление пользователями ──


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_moderator),
):
    """Список пользователей платформы.
    Доступен админу и модератору (модератор — только просмотр)."""
    return db.query(User).order_by(User.id).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Выставить статус и/или заблокировать/разблокировать пользователя.
    Только админ. Нельзя блокировать себя и других администраторов."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if payload.status is not None:
        # Пустая строка — снять статус
        status_value = payload.status.strip().lstrip("#").strip()
        user.status = status_value or None

    if payload.is_blocked is not None:
        if payload.is_blocked:
            if user.id == admin.id:
                raise HTTPException(400, "You cannot block yourself")
            if user.role == UserRole.admin:
                raise HTTPException(400, "You cannot block an administrator")
        user.is_blocked = payload.is_blocked

    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}/role", response_model=UserOut)
def set_user_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Назначить роль пользователю (student / moderator / admin). Только админ."""
    try:
        new_role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(400, f"Unknown role: {payload.role}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and new_role != UserRole.admin:
        raise HTTPException(400, "You cannot demote yourself")

    user.role = new_role
    db.commit()
    db.refresh(user)
    return user
