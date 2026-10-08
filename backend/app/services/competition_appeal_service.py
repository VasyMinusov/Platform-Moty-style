"""Апелляции участников соревнования."""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import User
from ..models_competitions import (
    AppealStatus,
    Competition,
    CompetitionAppeal,
    CompetitionChallenge,
)
from . import competition_audit


def create_appeal(
    db: Session,
    comp: Competition,
    user: User,
    *,
    message: str,
    challenge_id: Optional[int] = None,
) -> CompetitionAppeal:
    if challenge_id is not None:
        ch = (
            db.query(CompetitionChallenge)
            .filter_by(id=challenge_id, competition_id=comp.id)
            .first()
        )
        if not ch:
            raise HTTPException(404, "Challenge not found")

    # Уже есть открытая?
    existing = (
        db.query(CompetitionAppeal)
        .filter_by(
            competition_id=comp.id, user_id=user.id,
            challenge_id=challenge_id, status=AppealStatus.open,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "You already have an open appeal for this challenge")

    appeal = CompetitionAppeal(
        competition_id=comp.id,
        user_id=user.id,
        challenge_id=challenge_id,
        message=message,
        status=AppealStatus.open,
    )
    db.add(appeal)
    competition_audit.log_action(
        db, competition_id=comp.id, actor=user,
        action="appeal.create",
        target_type="appeal", target_id=None,
        payload={"challenge_id": challenge_id},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


def list_appeals(
    db: Session, comp: Competition, *,
    status: Optional[str] = None,
    only_mine_user_id: Optional[int] = None,
) -> list[CompetitionAppeal]:
    q = db.query(CompetitionAppeal).filter_by(competition_id=comp.id)
    if status:
        q = q.filter(CompetitionAppeal.status == AppealStatus(status))
    if only_mine_user_id is not None:
        q = q.filter(CompetitionAppeal.user_id == only_mine_user_id)
    return q.order_by(CompetitionAppeal.created_at.desc()).all()


def resolve_appeal(
    db: Session,
    comp: Competition,
    appeal_id: int,
    *,
    status: str,
    resolution: Optional[str],
    actor: User,
) -> CompetitionAppeal:
    if status not in ("accepted", "rejected"):
        raise HTTPException(400, "status must be accepted or rejected")

    appeal = (
        db.query(CompetitionAppeal)
        .filter_by(id=appeal_id, competition_id=comp.id)
        .first()
    )
    if not appeal:
        raise HTTPException(404, "Appeal not found")
    if appeal.status != AppealStatus.open:
        raise HTTPException(409, "Appeal is already resolved")

    appeal.status = AppealStatus(status)
    appeal.resolution = resolution
    appeal.resolved_by = actor.id
    appeal.resolved_at = datetime.utcnow()

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action=f"appeal.{status}",
        target_type="appeal", target_id=appeal.id,
        payload={"resolution": resolution},
    )
    db.commit()
    db.refresh(appeal)
    return appeal