"""Админский дашборд и ручная корректировка очков."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..models_competitions import ScoreEventReason
from ..schemas_competitions import (
    DashboardOut, ScoreAdjustRequest, ScoreAdjustResult,
)
from ..security import competition_moderator_required
from ..services import competition_audit
from ..services import competition_dashboard_service as dash
from ..services import competition_service, competition_scoring_service as cs


router = APIRouter(prefix="/admin/competitions", tags=["competitions:dashboard"])


@router.get("/{slug}/dashboard", response_model=DashboardOut)
def get_dashboard(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)
    data = dash.compute(db, comp)
    return DashboardOut(
        competition_id=data.competition_id,
        slug=data.slug,
        generated_at=data.generated_at,
        participants=data.participants,
        challenges=data.challenges,
        solves=data.solves,
        score_distribution=data.score_distribution,
        solves_timeline=data.solves_timeline,
        first_bloods=data.first_bloods,
        top_solvers=data.top_solvers,
        category_activity=data.category_activity,
        anomalies=data.anomalies,
    )


@router.post("/{slug}/score-adjust", response_model=ScoreAdjustResult)
def adjust_score(
    slug: str,
    payload: ScoreAdjustRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(competition_moderator_required()),
):
    comp = competition_service.get_by_slug(db, slug)

    # Событие в аудит + новое score event с reason=manual.
    from ..models_competitions import CompetitionScoreEvent
    event = CompetitionScoreEvent(
        competition_id=comp.id,
        user_id=payload.user_id,
        team_id=payload.team_id,
        delta=payload.delta,
        reason=ScoreEventReason.manual,
    )
    db.add(event)
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="score.manual_adjust",
        target_type="user" if payload.user_id else "team",
        target_id=payload.user_id or payload.team_id,
        payload={"delta": payload.delta, "comment": payload.comment},
    )
    db.commit()

    total = cs.total_score(
        db, comp,
        user_id=payload.user_id if payload.team_id is None else None,
        team_id=payload.team_id,
    )
    return ScoreAdjustResult(delta=payload.delta, total=total)