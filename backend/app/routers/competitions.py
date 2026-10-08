"""Роутер модуля «Соревнования».

Публичные и админские endpoint'ы в одном файле, разделены префиксами:
  /competitions/*              — публичные и для участников
  /admin/competitions/*        — админ/модератор
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserRole
from ..models_competitions import CompetitionStatus
from ..schemas_competitions import (
    ApplicationCreate, ApplicationDecision, ApplicationOut,
    AuditOut, CompetitionCreate, CompetitionListItem, CompetitionOut,
    CompetitionUpdate, ModeratorAdd, ModeratorOut,
)
from ..security import (
    get_current_user, require_admin, require_staff,
    competition_moderator_required,
)
from ..services import competition_audit, competition_service

router = APIRouter(prefix="/competitions", tags=["competitions"])
admin_router = APIRouter(prefix="/admin/competitions", tags=["competitions:admin"])


# ══════════════════════════════════════════════════════════════════════
# Публичные / для участников
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_model=list[CompetitionListItem])
def list_competitions(
    status: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    return competition_service.list_competitions(
        db, user=user, status=status, visibility=visibility,
    )


@router.get("/{slug}", response_model=CompetitionOut)
def get_competition(
    slug: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    c = competition_service.get_by_slug(db, slug)
    if not competition_service.can_view(db, c, user):
        raise HTTPException(403, "Forbidden")
    return c


@router.post("/{slug}/apply", response_model=ApplicationOut)
def apply(
    slug: str,
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = competition_service.get_by_slug(db, slug)
    a = competition_service.apply_to_competition(
        db, c, user, payload.motivation, payload.comment,
    )
    return _application_out(db, a)


@router.delete("/{slug}/apply", response_model=ApplicationOut)
def withdraw(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = competition_service.get_by_slug(db, slug)
    a = competition_service.withdraw_application(db, c, user)
    return _application_out(db, a)


@router.get("/{slug}/my-application", response_model=Optional[ApplicationOut])
def my_application(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..models_competitions import CompetitionApplication
    c = competition_service.get_by_slug(db, slug)
    a = db.query(CompetitionApplication).filter_by(
        competition_id=c.id, user_id=user.id,
    ).first()
    return _application_out(db, a) if a else None


# ══════════════════════════════════════════════════════════════════════
# Админ / модератор
# ══════════════════════════════════════════════════════════════════════

@admin_router.get("", response_model=list[CompetitionListItem])
def admin_list_competitions(
    status: Optional[str] = Query(None),
    only_mine: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return competition_service.list_competitions(
        db, user=user, status=status, only_mine=only_mine, include_hidden=True,
    )


@admin_router.post("", response_model=CompetitionOut, status_code=201)
def admin_create_competition(
    payload: CompetitionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return competition_service.create_competition(db, payload, user)


@admin_router.get("/{slug}", response_model=CompetitionOut)
def admin_get_competition(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    return competition_service.get_by_slug(db, slug)


@admin_router.patch("/{slug}", response_model=CompetitionOut)
def admin_update_competition(
    slug: str,
    payload: CompetitionUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.update_competition(db, c, payload, actor)


@admin_router.delete("/{slug}")
def admin_delete_competition(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    c = competition_service.get_by_slug(db, slug)
    competition_service.soft_delete(db, c, actor)
    return {"deleted": True}


# ── Статусы ──────────────────────────────────────────────────────────

@admin_router.post("/{slug}/publish", response_model=CompetitionOut)
def admin_publish(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),  # публикует только админ
):
    """draft -> announced. Только админ."""
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.announced, actor,
    )


@admin_router.post("/{slug}/open-registration", response_model=CompetitionOut)
def admin_open_registration(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.registration_open, actor,
    )


@admin_router.post("/{slug}/close-registration", response_model=CompetitionOut)
def admin_close_registration(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.registration_closed, actor,
    )


@admin_router.post("/{slug}/start", response_model=CompetitionOut)
def admin_start(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.running, actor,
    )


@admin_router.post("/{slug}/pause", response_model=CompetitionOut)
def admin_pause(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.paused, actor,
    )


@admin_router.post("/{slug}/resume", response_model=CompetitionOut)
def admin_resume(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.running, actor,
    )


@admin_router.post("/{slug}/finish", response_model=CompetitionOut)
def admin_finish(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.finished, actor,
    )


@admin_router.post("/{slug}/cancel", response_model=CompetitionOut)
def admin_cancel(
    slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    return competition_service.transition_status(
        db, c, CompetitionStatus.cancelled, actor,
    )


# ── Модераторы ───────────────────────────────────────────────────────

@admin_router.get("/{slug}/moderators", response_model=list[ModeratorOut])
def admin_list_moderators(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    rows = competition_service.list_moderators(db, c)
    out = []
    for m in rows:
        u = db.query(User).filter(User.id == m.user_id).first()
        out.append(ModeratorOut(
            user_id=m.user_id,
            username=u.username if u else "?",
            role=m.role.value,
            added_by=m.added_by,
            added_at=m.added_at,
        ))
    return out


@admin_router.post("/{slug}/moderators", response_model=ModeratorOut, status_code=201)
def admin_add_moderator(
    slug: str,
    payload: ModeratorAdd,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),  # назначать может только админ
):
    c = competition_service.get_by_slug(db, slug)
    m = competition_service.add_moderator(db, c, payload, actor)
    u = db.query(User).filter(User.id == m.user_id).first()
    return ModeratorOut(
        user_id=m.user_id,
        username=u.username if u else "?",
        role=m.role.value,
        added_by=m.added_by,
        added_at=m.added_at,
    )


@admin_router.delete("/{slug}/moderators/{user_id}")
def admin_remove_moderator(
    slug: str,
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    c = competition_service.get_by_slug(db, slug)
    competition_service.remove_moderator(db, c, user_id, actor)
    return {"deleted": True}


# ── Заявки ───────────────────────────────────────────────────────────

@admin_router.get("/{slug}/applications", response_model=list[ApplicationOut])
def admin_list_applications(
    slug: str,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    rows = competition_service.list_applications(db, c, status)
    return [_application_out(db, a) for a in rows]


@admin_router.patch("/{slug}/applications/{application_id}", response_model=ApplicationOut)
def admin_decide_application(
    slug: str,
    application_id: int,
    payload: ApplicationDecision,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    c = competition_service.get_by_slug(db, slug)
    a = competition_service.decide_application(db, c, application_id, payload, actor)
    return _application_out(db, a)


# ── Аудит ────────────────────────────────────────────────────────────

@admin_router.get("/{slug}/audit", response_model=list[AuditOut])
def admin_audit(
    slug: str,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    from ..models_competitions import CompetitionAuditLog
    c = competition_service.get_by_slug(db, slug)
    rows = (
        db.query(CompetitionAuditLog)
        .filter_by(competition_id=c.id)
        .order_by(CompetitionAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows


# ── Helper ───────────────────────────────────────────────────────────

def _application_out(db: Session, a) -> Optional[ApplicationOut]:
    if a is None:
        return None
    u = db.query(User).filter(User.id == a.user_id).first()
    return ApplicationOut(
        id=a.id,
        competition_id=a.competition_id,
        user_id=a.user_id,
        username=u.username if u else "?",
        team_id=a.team_id,
        motivation=a.motivation,
        comment=a.comment,
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        applied_at=a.applied_at,
        decided_at=a.decided_at,
        decided_by=a.decided_by,
        decision_comment=a.decision_comment,
    )