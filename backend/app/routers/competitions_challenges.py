"""Роутер заданий соревнования.

Публичные endpoints — просмотр и скачивание файлов (kind=static).
Admin endpoints — загрузка ZIP, обновление, удаление, rebuild, промоушен.
"""
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..models_competitions import (
    BuildStatus, ChallengeKind, ChallengeVisibility, CompetitionStatus,
    CompetitionTeamMember, TeamMemberStatus,
)
from ..schemas_competitions import (
    BuildStatusOut, CompetitionChallengeOut, CompetitionChallengeUpdate,
    PromoteChallengeRequest,
)
from ..security import (
    get_current_user, require_admin, competition_moderator_required,
)
from ..services import competition_challenge_service as cc_service
from ..services import competition_service, competition_team_service

router = APIRouter(prefix="/competitions", tags=["competitions:challenges"])
admin_router = APIRouter(prefix="/admin/competitions", tags=["competitions:challenges:admin"])


# ── Helper: узнать team_id текущего пользователя в соревновании ──────

def _team_id_of(db: Session, comp, user: User) -> Optional[int]:
    team = (
        db.query(CompetitionTeamMember)
        .join(
            # join с CompetitionTeam, чтобы отфильтровать по competition_id
            # (используем competition_team_service.get_my_team для простоты)
            __import__("app.models_competitions", fromlist=["CompetitionTeam"]).CompetitionTeam,
            __import__("app.models_competitions", fromlist=["CompetitionTeam"]).CompetitionTeam.id
            == CompetitionTeamMember.team_id,
        )
        .filter(
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status == TeamMemberStatus.accepted,
        )
        .first()
    )
    if not team:
        return None
    # проверим, что команда в этом соревновании
    t = competition_team_service.get_my_team(db, comp, user)
    return t.id if t else None


def _serialize_challenge(
    db: Session, ch, user: Optional[User], comp,
) -> CompetitionChallengeOut:
    team_id = _team_id_of(db, comp, user) if user else None
    solved = cc_service.is_solved_by(
        db, ch,
        user_id=user.id if user else None,
        team_id=team_id,
    )
    data = CompetitionChallengeOut.model_validate(ch)
    data.solved = solved
    return data


# ══════════════════════════════════════════════════════════════════════
# Публичные / для участников
# ══════════════════════════════════════════════════════════════════════

@router.get("/{slug}/challenges", response_model=list[CompetitionChallengeOut])
def list_public_challenges(
    slug: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)

    # До старта обычные участники видят только visibility=visible.
    # После старта — visible и visible_after_start.
    started = comp.status in (
        CompetitionStatus.running, CompetitionStatus.paused,
        CompetitionStatus.finished,
    )
    items = cc_service.list_challenges(
        db, comp,
        include_disabled=False,
        include_hidden=False,
    )
    out = []
    for ch in items:
        if ch.visibility == ChallengeVisibility.visible_after_start and not started:
            continue
        out.append(_serialize_challenge(db, ch, user, comp))
    return out


@router.get("/{slug}/challenges/{ch_slug}", response_model=CompetitionChallengeOut)
def get_public_challenge(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    if not ch.enabled or ch.visibility == ChallengeVisibility.hidden:
        raise HTTPException(404, "Challenge not found")
    started = comp.status in (
        CompetitionStatus.running, CompetitionStatus.paused,
        CompetitionStatus.finished,
    )
    if ch.visibility == ChallengeVisibility.visible_after_start and not started:
        raise HTTPException(404, "Challenge not found")
    return _serialize_challenge(db, ch, user, comp)


@router.get("/{slug}/challenges/{ch_slug}/files/{file_id}")
def download_file(
    slug: str,
    ch_slug: str,
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    if not ch.enabled or ch.visibility == ChallengeVisibility.hidden:
        raise HTTPException(404, "Challenge not found")

    from ..models_competitions import CompetitionChallengeFile
    f = (
        db.query(CompetitionChallengeFile)
        .filter_by(id=file_id, challenge_id=ch.id, is_public=True)
        .first()
    )
    if not f:
        raise HTTPException(404, "File not found")

    p = Path(f.stored_path)
    if not p.exists():
        raise HTTPException(404, "File is missing on disk")

    return FileResponse(p, filename=f.filename, media_type=f.mime or "application/octet-stream")


# ══════════════════════════════════════════════════════════════════════
# Админ / модератор
# ══════════════════════════════════════════════════════════════════════

@admin_router.get(
    "/{slug}/challenges", response_model=list[CompetitionChallengeOut],
)
def admin_list_challenges(
    slug: str,
    include_disabled: bool = Query(True),
    include_hidden: bool = Query(True),
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    items = cc_service.list_challenges(
        db, comp, include_disabled=include_disabled, include_hidden=include_hidden,
    )
    return [_serialize_challenge(db, ch, actor, comp) for ch in items]


@admin_router.post(
    "/{slug}/challenges/upload",
    response_model=CompetitionChallengeOut,
    status_code=201,
)
async def admin_upload_challenge(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = await cc_service.upload_zip(db, comp, file, actor)
    return _serialize_challenge(db, ch, actor, comp)


@admin_router.get(
    "/{slug}/challenges/{ch_slug}", response_model=CompetitionChallengeOut,
)
def admin_get_challenge(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    return _serialize_challenge(db, ch, actor, comp)


@admin_router.patch(
    "/{slug}/challenges/{ch_slug}", response_model=CompetitionChallengeOut,
)
def admin_update_challenge(
    slug: str,
    ch_slug: str,
    payload: CompetitionChallengeUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    ch = cc_service.update_challenge(db, comp, ch, payload, actor)
    return _serialize_challenge(db, ch, actor, comp)


@admin_router.delete("/{slug}/challenges/{ch_slug}")
def admin_delete_challenge(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    cc_service.delete_challenge(db, comp, ch, actor)
    return {"deleted": True}


@admin_router.post(
    "/{slug}/challenges/{ch_slug}/rebuild", response_model=BuildStatusOut,
)
def admin_rebuild_challenge(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    if ch.kind != ChallengeKind.docker:
        raise HTTPException(400, "Only kind=docker can be rebuilt")
    cc_service.start_build(db, comp, ch, actor)
    db.refresh(ch)
    return BuildStatusOut(
        challenge_id=ch.id,
        slug=ch.slug,
        build_status=ch.build_status.value,
        build_log=ch.build_log,
        updated_at=ch.uploaded_at,
    )


@admin_router.get(
    "/{slug}/challenges/{ch_slug}/build-status", response_model=BuildStatusOut,
)
def admin_build_status(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    return BuildStatusOut(
        challenge_id=ch.id,
        slug=ch.slug,
        build_status=ch.build_status.value,
        build_log=ch.build_log,
        updated_at=ch.uploaded_at,
    )


@admin_router.post(
    "/{slug}/challenges/{ch_slug}/promote",
)
def admin_promote_challenge(
    slug: str,
    ch_slug: str,
    payload: PromoteChallengeRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    challenge = cc_service.promote_to_global(
        db, comp, ch, actor,
        new_slug=payload.new_slug,
        points=payload.points,
        enabled=payload.enabled,
    )
    return {
        "global_challenge_id": challenge.id,
        "slug": challenge.slug,
    }