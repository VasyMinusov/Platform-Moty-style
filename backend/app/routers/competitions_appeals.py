"""Апелляции соревнования."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas_competitions import (
    AppealCreate, AppealOut, AppealResolve,
)
from ..security import (
    get_current_user, competition_moderator_required,
)
from ..services import competition_appeal_service as appeals
from ..services import competition_service


router = APIRouter(prefix="/competitions", tags=["competitions:appeals"])
admin_router = APIRouter(prefix="/admin/competitions", tags=["competitions:appeals:admin"])


def _to_out(db: Session, a) -> AppealOut:
    u = db.query(User).filter(User.id == a.user_id).first()
    return AppealOut(
        id=a.id,
        competition_id=a.competition_id,
        user_id=a.user_id,
        username=u.username if u else "?",
        challenge_id=a.challenge_id,
        message=a.message,
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        resolved_by=a.resolved_by,
        resolved_at=a.resolved_at,
        resolution=a.resolution,
        created_at=a.created_at,
    )


# ── Участник ────────────────────────────────────────────────────────

@router.post("/{slug}/appeals", response_model=AppealOut, status_code=201)
def create_appeal(
    slug: str,
    payload: AppealCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    a = appeals.create_appeal(
        db, comp, user,
        message=payload.message,
        challenge_id=payload.challenge_id,
    )
    return _to_out(db, a)


@router.get("/{slug}/my-appeals", response_model=list[AppealOut])
def my_appeals(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    rows = appeals.list_appeals(db, comp, only_mine_user_id=user.id)
    return [_to_out(db, a) for a in rows]


# ── Админ / модератор ───────────────────────────────────────────────

@admin_router.get("/{slug}/appeals", response_model=list[AppealOut])
def admin_list_appeals(
    slug: str,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    rows = appeals.list_appeals(db, comp, status=status)
    return [_to_out(db, a) for a in rows]


@admin_router.patch("/{slug}/appeals/{appeal_id}", response_model=AppealOut)
def admin_resolve_appeal(
    slug: str,
    appeal_id: int,
    payload: AppealResolve,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    a = appeals.resolve_appeal(
        db, comp, appeal_id,
        status=payload.status,
        resolution=payload.resolution,
        actor=actor,
    )
    return _to_out(db, a)