"""Роутер команд соревнования."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas_competitions import (
    TeamCreate, TeamJoinByCode, TeamInvite, TeamOut, TeamSummary, TeamUpdate,
)
from ..security import get_current_user
from ..services import competition_service, competition_team_service

router = APIRouter(prefix="/competitions", tags=["competitions:teams"])


def _serialize(
    db: Session, team, user: Optional[User], *,
    include_invite_code: bool = False,
) -> TeamOut:
    return TeamOut(**competition_team_service.serialize_team(
        db, team, include_invite_code=include_invite_code,
    ))


def _user_can_see_roster(db: Session, comp, user: User, team) -> bool:
    if comp.public_team_roster:
        return True
    if user.id == team.captain_id:
        return True
    # Приглашён или в команде?
    from ..models_competitions import CompetitionTeamMember, TeamMemberStatus
    m = (
        db.query(CompetitionTeamMember)
        .filter(
            CompetitionTeamMember.team_id == team.id,
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status.in_(
                [TeamMemberStatus.accepted, TeamMemberStatus.invited]
            ),
        )
        .first()
    )
    return m is not None


# ── Список и карточки ────────────────────────────────────────────────

@router.get("/{slug}/teams", response_model=list[TeamSummary])
def list_teams(
    slug: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    teams = competition_team_service.list_teams(db, comp, user)
    out = []
    for t in teams:
        s = competition_team_service.serialize_team(db, t, include_invite_code=False)
        out.append(TeamSummary(
            id=s["id"],
            name=s["name"],
            captain_username=s["captain_username"],
            status=s["status"],
            member_count=s["member_count"],
        ))
    return out


@router.get("/{slug}/teams/{team_id}", response_model=TeamOut)
def get_team(
    slug: str,
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    if not _user_can_see_roster(db, comp, user, team):
        raise HTTPException(403, "Forbidden")
    return _serialize(db, team, user, include_invite_code=True)


@router.get("/{slug}/my-team", response_model=Optional[TeamOut])
def get_my_team(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service.get_my_team(db, comp, user)
    if not team:
        return None
    return _serialize(db, team, user, include_invite_code=True)


@router.get("/{slug}/my-invitations", response_model=list[TeamOut])
def my_invitations(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    teams = competition_team_service.list_my_invitations(db, comp, user)
    return [_serialize(db, t, user, include_invite_code=False) for t in teams]


# ── Создание / изменение / удаление ──────────────────────────────────

@router.post("/{slug}/teams", response_model=TeamOut, status_code=201)
def create_team(
    slug: str,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service.create_team(db, comp, payload.name, user)
    return _serialize(db, team, user, include_invite_code=True)


@router.patch("/{slug}/teams/{team_id}", response_model=TeamOut)
def rename_team(
    slug: str,
    team_id: int,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    if payload.name is not None:
        team = competition_team_service.rename_team(db, comp, team, payload.name, user)
    return _serialize(db, team, user, include_invite_code=True)


@router.delete("/{slug}/teams/{team_id}")
def disband_team(
    slug: str,
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.disband_team(db, comp, team, user)
    return {"deleted": True}


# ── Приглашения ──────────────────────────────────────────────────────

@router.post("/{slug}/teams/{team_id}/invite", response_model=TeamOut)
def invite(
    slug: str,
    team_id: int,
    payload: TeamInvite,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.invite_user(db, comp, team, payload.username, user)
    return _serialize(db, team, user, include_invite_code=True)


@router.post("/{slug}/teams/{team_id}/invite/accept", response_model=TeamOut)
def accept_invite(
    slug: str,
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.accept_invite(db, comp, team, user)
    return _serialize(db, team, user, include_invite_code=True)


@router.post("/{slug}/teams/{team_id}/invite/decline")
def decline_invite(
    slug: str,
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.decline_invite(db, comp, team, user)
    return {"declined": True}


@router.post("/{slug}/teams/join-by-code", response_model=TeamOut)
def join_by_code(
    slug: str,
    payload: TeamJoinByCode,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    competition_team_service.join_by_code(db, comp, payload.invite_code, user)
    team = competition_team_service.get_my_team(db, comp, user)
    return _serialize(db, team, user, include_invite_code=True)


# ── Участники ────────────────────────────────────────────────────────

@router.delete("/{slug}/teams/{team_id}/members/{user_id}")
def kick_member(
    slug: str,
    team_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.kick_member(db, comp, team, user_id, user)
    return {"kicked": True}


@router.post("/{slug}/teams/{team_id}/leave")
def leave_team(
    slug: str,
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    team = competition_team_service._get_team(db, comp.id, team_id)
    competition_team_service.leave_team(db, comp, team, user)
    return {"left": True}