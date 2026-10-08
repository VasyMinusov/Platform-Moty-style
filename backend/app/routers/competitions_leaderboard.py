"""Публичный/участнический лидерборд и экспорт."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..models_competitions import (
    ApplicationStatus,
    CompetitionApplication,
    CompetitionTeam,
    CompetitionTeamMember,
    LeaderboardVisibility,
    TeamMemberStatus,
)
from ..schemas_competitions import LeaderboardRowOut, LeaderboardSnapshotOut
from ..security import get_current_user
from ..services import competition_leaderboard_service as lb
from ..services import competition_service


router = APIRouter(prefix="/competitions", tags=["competitions:leaderboard"])


def _is_participant(db: Session, comp, user: Optional[User]) -> bool:
    if user is None:
        return False
    if user.role.value in ("admin", "moderator"):
        return True
    app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=comp.id, user_id=user.id)
        .first()
    )
    if app and app.status == ApplicationStatus.approved:
        return True
    # Через команду
    team_ids = [
        t.id for (t,) in (
            db.query(CompetitionTeam.id)
            .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
            .filter(
                CompetitionTeam.competition_id == comp.id,
                CompetitionTeamMember.user_id == user.id,
                CompetitionTeamMember.status == TeamMemberStatus.accepted,
            )
            .all()
        )
    ]
    if team_ids:
        team_app = (
            db.query(CompetitionApplication)
            .filter(
                CompetitionApplication.competition_id == comp.id,
                CompetitionApplication.team_id.in_(team_ids),
                CompetitionApplication.status == ApplicationStatus.approved,
            )
            .first()
        )
        if team_app:
            return True
    return False


def _to_out(row: lb.LeaderboardRow) -> LeaderboardRowOut:
    return LeaderboardRowOut(
        rank=row.rank,
        id=row.id,
        name=row.name,
        score=row.score,
        solves_count=row.solves_count,
        last_solve_at=row.last_solve_at,
        first_solve_at=row.first_solve_at,
        is_team=row.is_team,
        members=row.members,
    )


@router.get("/{slug}/leaderboard", response_model=LeaderboardSnapshotOut)
def get_leaderboard(
    slug: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)

    vis = comp.leaderboard_visibility
    vis_val = vis.value if hasattr(vis, "value") else str(vis)

    if vis_val == LeaderboardVisibility.hidden.value:
        if not (user and user.role.value in ("admin", "moderator")):
            raise HTTPException(403, "Leaderboard is hidden")

    if vis_val == LeaderboardVisibility.participants.value:
        if not _is_participant(db, comp, user):
            raise HTTPException(403, "Leaderboard is for participants only")

    snapshot = lb.compute(db, comp)
    return LeaderboardSnapshotOut(
        competition_id=snapshot.competition_id,
        competition_slug=snapshot.competition_slug,
        mode=snapshot.mode,
        generated_at=snapshot.generated_at,
        individuals=[_to_out(r) for r in snapshot.individuals],
        teams=[_to_out(r) for r in snapshot.teams],
    )


@router.get("/{slug}/leaderboard/export", response_class=PlainTextResponse)
def export_leaderboard(
    slug: str,
    format: str = Query("csv", pattern="^(csv)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)

    # Экспорт доступен только админу/модератору соревнования.
    if user.role.value not in ("admin", "moderator"):
        raise HTTPException(403, "Admin or moderator only")

    snapshot = lb.compute(db, comp)
    csv_data = lb.to_csv(snapshot)

    filename = f"leaderboard-{comp.slug}-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )