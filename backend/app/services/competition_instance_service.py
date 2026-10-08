"""Сервис запуска/остановки инстансов соревнования.

Оборачивает orchestrator.start_competition_instance, добавляя проверки:
- статус соревнования (running)
- пользователь допущен (approved или в approved-команде)
- задание включено и видимо
- зависимости задания решены
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import ChallengeInstance, User
from ..models_competitions import (
    ApplicationStatus,
    ChallengeVisibility,
    Competition,
    CompetitionApplication,
    CompetitionChallenge,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
    TeamMemberStatus,
    TeamStatus,
)
from . import orchestrator
from . import competition_challenge_service as cc_service


def _user_team(db: Session, comp: Competition, user: User) -> Optional[CompetitionTeam]:
    return (
        db.query(CompetitionTeam)
        .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status == TeamMemberStatus.accepted,
            CompetitionTeam.status == TeamStatus.approved,
        )
        .first()
    )


def _ensure_participation(db: Session, comp: Competition, user: User) -> Optional[int]:
    """Возвращает team_id, если пользователь участвует как команда, иначе None.
    Бросает 403, если пользователь не допущен."""
    if user.role.value in ("admin", "moderator"):
        # Сотрудники платформы могут тестировать инстансы без заявки.
        team = _user_team(db, comp, user)
        return team.id if team else None

    # Индивидуальная заявка?
    app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=comp.id, user_id=user.id)
        .first()
    )
    if app and app.status == ApplicationStatus.approved and app.team_id is None:
        return None

    # Командная?
    team = _user_team(db, comp, user)
    if team is not None:
        team_app = (
            db.query(CompetitionApplication)
            .filter_by(competition_id=comp.id, team_id=team.id)
            .first()
        )
        if team_app and team_app.status == ApplicationStatus.approved:
            return team.id

    raise HTTPException(403, "You are not approved for this competition")


def _ensure_dependencies_solved(
    db: Session, ch: CompetitionChallenge, *,
    user_id: int, team_id: Optional[int],
) -> None:
    deps = ch.dependencies_json or []
    if not deps:
        return
    from ..models_competitions import CompetitionSolve

    for dep_slug in deps:
        dep_ch = (
            db.query(CompetitionChallenge)
            .filter_by(competition_id=ch.competition_id, slug=dep_slug)
            .first()
        )
        if not dep_ch:
            raise HTTPException(409, f"Dependency {dep_slug} not found")
        q = db.query(CompetitionSolve).filter_by(challenge_id=dep_ch.id)
        if team_id is not None:
            q = q.filter_by(team_id=team_id)
        else:
            q = q.filter_by(user_id=user_id)
        if not q.first():
            raise HTTPException(
                409,
                f"Solve {dep_slug} before starting this challenge",
            )


def start(
    db: Session, comp: Competition, ch: CompetitionChallenge, user: User,
) -> ChallengeInstance:
    if comp.status != CompetitionStatus.running:
        raise HTTPException(409, "Competition is not running")
    if not ch.enabled:
        raise HTTPException(404, "Challenge disabled")
    if ch.visibility == ChallengeVisibility.hidden:
        raise HTTPException(404, "Challenge not available")

    if ch.kind.value != "docker":
        raise HTTPException(400, "Static challenges do not need an instance")

    team_id = _ensure_participation(db, comp, user)
    _ensure_dependencies_solved(db, ch, user_id=user.id, team_id=team_id)

    # Проверка: не решено ли уже?
    if cc_service.is_solved_by(db, ch, user_id=user.id, team_id=team_id):
        raise HTTPException(409, "Challenge already solved")

    try:
        return orchestrator.start_competition_instance(
            db, comp, ch, user_id=user.id, team_id=team_id,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))


def stop(
    db: Session, comp: Competition, ch: CompetitionChallenge, user: User,
) -> None:
    team_id = _user_team(db, comp, user).id if _user_team(db, comp, user) else None

    q = db.query(ChallengeInstance).filter_by(
        competition_id=comp.id, challenge_id=ch.id, status="running",
    )
    if team_id is not None:
        q = q.filter_by(team_id=team_id)
    else:
        q = q.filter_by(user_id=user.id)
    instance = q.first()
    if not instance:
        raise HTTPException(404, "No running instance")

    orchestrator.stop_competition_instance(db, instance)