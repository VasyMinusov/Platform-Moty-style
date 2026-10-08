"""Сервис команд соревнования.

Правила:
- Создаёт команду пользователь — он становится капитаном и автоматически
  её первым принятым участником.
- На капитана заводится CompetitionApplication (одна на команду), её
  статус автоматически пересчитывается при изменении состава:
    * team_pending — пока не набран min_team_size
    * pending      — минимум набран, ждём решения админа/модератора
    * approved/rejected/withdrawn — после решения или отзыва
- Один пользователь — не более одной активной команды в рамках
  соревнования (ни как капитан, ни как участник).
- Приглашать можно по username или по invite-коду команды.
"""
import secrets
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User, UserRole
from ..models_competitions import (
    ApplicationStatus,
    Competition,
    CompetitionApplication,
    CompetitionMode,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
    TeamMemberRole,
    TeamMemberStatus,
    TeamStatus,
)
from . import competition_audit


# ── Вспомогательные ──────────────────────────────────────────────────

def _generate_invite_code() -> str:
    # 16 символов url-safe, без похожих символов
    return secrets.token_urlsafe(12)[:16]


def _accepted_size(db: Session, team_id: int) -> int:
    return (
        db.query(func.count(CompetitionTeamMember.user_id))
        .filter(
            CompetitionTeamMember.team_id == team_id,
            CompetitionTeamMember.status == TeamMemberStatus.accepted,
        )
        .scalar()
        or 0
    )


def _is_moderator_of(db: Session, competition_id: int, user: User) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.role != UserRole.moderator:
        return False
    from ..models_competitions import CompetitionModerator
    return (
        db.query(CompetitionModerator)
        .filter_by(competition_id=competition_id, user_id=user.id)
        .first()
        is not None
    )


def _ensure_team_mode(comp: Competition) -> None:
    if comp.mode not in (CompetitionMode.team, CompetitionMode.both):
        raise HTTPException(400, "Competition does not support teams")


def _ensure_registration_open(comp: Competition) -> None:
    if comp.status != CompetitionStatus.registration_open:
        raise HTTPException(409, "Registration is not open for this competition")
    if comp.registration_closes_at and datetime.utcnow() > comp.registration_closes_at \
            and not comp.allow_late_application:
        raise HTTPException(409, "Registration is closed")


def _get_team(db: Session, competition_id: int, team_id: int) -> CompetitionTeam:
    team = (
        db.query(CompetitionTeam)
        .filter_by(id=team_id, competition_id=competition_id)
        .first()
    )
    if not team:
        raise HTTPException(404, "Team not found")
    return team


def _get_member(db: Session, team_id: int, user_id: int) -> Optional[CompetitionTeamMember]:
    return (
        db.query(CompetitionTeamMember)
        .filter_by(team_id=team_id, user_id=user_id)
        .first()
    )


def _active_team_of(db: Session, competition_id: int, user_id: int) -> Optional[CompetitionTeam]:
    """Возвращает команду, в которой пользователь — принятый участник или
    капитан, в рамках соревнования."""
    return (
        db.query(CompetitionTeam)
        .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
        .filter(
            CompetitionTeam.competition_id == competition_id,
            CompetitionTeamMember.user_id == user_id,
            CompetitionTeamMember.status.in_(
                [TeamMemberStatus.accepted, TeamMemberStatus.invited]
            ),
        )
        .first()
    )


def _recompute_application(db: Session, team: CompetitionTeam) -> None:
    """Пересчитывает статус командной заявки в зависимости от размера."""
    app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=team.competition_id, team_id=team.id)
        .first()
    )
    if not app:
        return
    if app.status in (
        ApplicationStatus.approved,
        ApplicationStatus.rejected,
        ApplicationStatus.withdrawn,
    ):
        return

    comp = db.query(Competition).filter(Competition.id == team.competition_id).first()
    min_size = (comp.min_team_size or 1) if comp else 1
    size = _accepted_size(db, team.id)

    if size >= min_size:
        app.status = ApplicationStatus.pending
        if team.status == TeamStatus.forming:
            team.status = TeamStatus.pending
    else:
        app.status = ApplicationStatus.team_pending
        if team.status == TeamStatus.pending:
            team.status = TeamStatus.forming


def _serialize_member(db: Session, m: CompetitionTeamMember) -> dict:
    u = db.query(User).filter(User.id == m.user_id).first()
    return {
        "user_id": m.user_id,
        "username": u.username if u else "?",
        "role": m.role.value if hasattr(m.role, "value") else str(m.role),
        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
        "invited_at": m.invited_at,
        "joined_at": m.joined_at,
    }


def serialize_team(
    db: Session, team: CompetitionTeam, *, include_invite_code: bool,
) -> dict:
    captain = db.query(User).filter(User.id == team.captain_id).first()
    comp = db.query(Competition).filter(Competition.id == team.competition_id).first()

    members_q = (
        db.query(CompetitionTeamMember)
        .filter(CompetitionTeamMember.team_id == team.id)
        .filter(CompetitionTeamMember.status.in_(
            [TeamMemberStatus.accepted, TeamMemberStatus.invited]
        ))
        .order_by(CompetitionTeamMember.role, CompetitionTeamMember.invited_at)
    )
    members = [_serialize_member(db, m) for m in members_q.all()]

    return {
        "id": team.id,
        "competition_id": team.competition_id,
        "name": team.name,
        "captain_id": team.captain_id,
        "captain_username": captain.username if captain else "?",
        "status": team.status.value if hasattr(team.status, "value") else str(team.status),
        "invite_code": team.invite_code if include_invite_code else None,
        "created_at": team.created_at,
        "members": members,
        "member_count": _accepted_size(db, team.id),
        "min_team_size": comp.min_team_size if comp else None,
        "max_team_size": comp.max_team_size if comp else None,
    }


# ── Создание / изменение / удаление ──────────────────────────────────

def create_team(
    db: Session, comp: Competition, name: str, captain: User,
) -> CompetitionTeam:
    _ensure_team_mode(comp)
    _ensure_registration_open(comp)

    # Уже в команде?
    if _active_team_of(db, comp.id, captain.id):
        raise HTTPException(409, "You are already in a team for this competition")

    # Уже подал индивидуальную заявку?
    existing_app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=comp.id, user_id=captain.id)
        .first()
    )
    if existing_app and existing_app.status not in (
        ApplicationStatus.withdrawn, ApplicationStatus.rejected,
    ):
        raise HTTPException(
            409,
            "You already have an application for this competition. "
            "Withdraw it first if you want to create a team.",
        )

    # Лимит команд
    if comp.max_teams is not None:
        team_count = (
            db.query(func.count(CompetitionTeam.id))
            .filter(CompetitionTeam.competition_id == comp.id)
            .scalar()
            or 0
        )
        if team_count >= comp.max_teams:
            raise HTTPException(409, "Maximum number of teams reached")

    # Уникальность имени в рамках соревнования
    clash = (
        db.query(CompetitionTeam)
        .filter_by(competition_id=comp.id, name=name)
        .first()
    )
    if clash:
        raise HTTPException(409, "Team with this name already exists")

    team = CompetitionTeam(
        competition_id=comp.id,
        name=name,
        captain_id=captain.id,
        status=TeamStatus.forming,
        invite_code=_generate_invite_code(),
    )
    db.add(team)
    db.flush()

    # Капитан — первый принятый участник.
    db.add(CompetitionTeamMember(
        team_id=team.id,
        user_id=captain.id,
        role=TeamMemberRole.captain,
        status=TeamMemberStatus.accepted,
        joined_at=datetime.utcnow(),
    ))

    # Заявка от имени команды (хранится на капитане).
    if existing_app:
        existing_app.team_id = team.id
        existing_app.status = ApplicationStatus.team_pending
        existing_app.applied_at = datetime.utcnow()
        existing_app.decided_at = None
        existing_app.decided_by = None
    else:
        db.add(CompetitionApplication(
            competition_id=comp.id,
            user_id=captain.id,
            team_id=team.id,
            status=ApplicationStatus.team_pending,
        ))

    _recompute_application(db, team)

    competition_audit.log_action(
        db, competition_id=comp.id, actor=captain,
        action="team.create", target_type="team", target_id=team.id,
        payload={"name": team.name},
    )
    db.commit()
    db.refresh(team)
    return team


def rename_team(
    db: Session, comp: Competition, team: CompetitionTeam, new_name: str, actor: User,
) -> CompetitionTeam:
    if team.captain_id != actor.id and actor.role != UserRole.admin:
        raise HTTPException(403, "Only the captain can rename the team")
    clash = (
        db.query(CompetitionTeam)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeam.name == new_name,
            CompetitionTeam.id != team.id,
        )
        .first()
    )
    if clash:
        raise HTTPException(409, "Team with this name already exists")
    team.name = new_name
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.rename", target_type="team", target_id=team.id,
        payload={"new_name": new_name},
    )
    db.commit()
    db.refresh(team)
    return team


def disband_team(db: Session, comp: Competition, team: CompetitionTeam, actor: User) -> None:
    if team.captain_id != actor.id and actor.role != UserRole.admin:
        raise HTTPException(403, "Only the captain can disband the team")
    # Отзываем заявку, если она не решена
    app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=comp.id, team_id=team.id)
        .first()
    )
    if app and app.status in (ApplicationStatus.pending, ApplicationStatus.team_pending):
        app.status = ApplicationStatus.withdrawn
        app.decided_at = datetime.utcnow()

    db.query(CompetitionTeamMember).filter_by(team_id=team.id).delete()
    db.delete(team)
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.disband", target_type="team", target_id=team.id,
    )
    db.commit()


# ── Приглашения ──────────────────────────────────────────────────────

def _ensure_captain(team: CompetitionTeam, actor: User) -> None:
    if team.captain_id != actor.id:
        raise HTTPException(403, "Only the captain can manage the team")


def invite_user(
    db: Session, comp: Competition, team: CompetitionTeam, username: str, actor: User,
) -> CompetitionTeamMember:
    _ensure_captain(team, actor)

    # Лимит состава
    if comp.max_team_size is not None:
        size = _accepted_size(db, team.id)
        pending_invites = (
            db.query(func.count(CompetitionTeamMember.user_id))
            .filter(
                CompetitionTeamMember.team_id == team.id,
                CompetitionTeamMember.status == TeamMemberStatus.invited,
            )
            .scalar()
            or 0
        )
        if size + pending_invites >= comp.max_team_size:
            raise HTTPException(409, "Team is already at max size")

    invitee = db.query(User).filter(User.username == username).first()
    if not invitee:
        raise HTTPException(404, "User not found")
    if invitee.id == actor.id:
        raise HTTPException(400, "You cannot invite yourself")

    # Уже принят в этой команде?
    existing = _get_member(db, team.id, invitee.id)
    if existing and existing.status == TeamMemberStatus.accepted:
        raise HTTPException(409, "User is already a member of this team")

    # Уже в другой команде этого соревнования?
    other = _active_team_of(db, comp.id, invitee.id)
    if other and other.id != team.id:
        raise HTTPException(409, "User is already in another team of this competition")

    # Есть ли уже приглашение в эту команду?
    if existing and existing.status == TeamMemberStatus.invited:
        raise HTTPException(409, "User is already invited")

    if existing:
        existing.status = TeamMemberStatus.invited
        existing.invited_at = datetime.utcnow()
        member = existing
    else:
        member = CompetitionTeamMember(
            team_id=team.id,
            user_id=invitee.id,
            role=TeamMemberRole.member,
            status=TeamMemberStatus.invited,
        )
        db.add(member)

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.invite", target_type="user", target_id=invitee.id,
        payload={"team_id": team.id},
    )
    db.commit()
    db.refresh(member)
    return member


def accept_invite(
    db: Session, comp: Competition, team: CompetitionTeam, actor: User,
) -> CompetitionTeamMember:
    m = _get_member(db, team.id, actor.id)
    if not m or m.status != TeamMemberStatus.invited:
        raise HTTPException(404, "Invitation not found")

    # Проверка: не принял ли уже другое приглашение в этом соревновании
    other = (
        db.query(CompetitionTeamMember)
        .join(CompetitionTeam, CompetitionTeam.id == CompetitionTeamMember.team_id)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeamMember.user_id == actor.id,
            CompetitionTeamMember.status == TeamMemberStatus.accepted,
            CompetitionTeamMember.team_id != team.id,
        )
        .first()
    )
    if other:
        raise HTTPException(409, "You are already in another team of this competition")

    # Максимум состава
    if comp.max_team_size is not None and _accepted_size(db, team.id) >= comp.max_team_size:
        raise HTTPException(409, "Team is full")

    m.status = TeamMemberStatus.accepted
    m.joined_at = datetime.utcnow()

    _recompute_application(db, team)

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.invite.accept", target_type="team", target_id=team.id,
    )
    db.commit()
    db.refresh(m)
    return m


def decline_invite(
    db: Session, comp: Competition, team: CompetitionTeam, actor: User,
) -> None:
    m = _get_member(db, team.id, actor.id)
    if not m or m.status != TeamMemberStatus.invited:
        raise HTTPException(404, "Invitation not found")
    m.status = TeamMemberStatus.declined
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.invite.decline", target_type="team", target_id=team.id,
    )
    db.commit()


def join_by_code(
    db: Session, comp: Competition, invite_code: str, actor: User,
) -> CompetitionTeamMember:
    _ensure_team_mode(comp)
    _ensure_registration_open(comp)

    if _active_team_of(db, comp.id, actor.id):
        raise HTTPException(409, "You are already in a team for this competition")

    team = (
        db.query(CompetitionTeam)
        .filter_by(competition_id=comp.id, invite_code=invite_code)
        .first()
    )
    if not team:
        raise HTTPException(404, "Invalid invite code")

    if comp.max_team_size is not None and _accepted_size(db, team.id) >= comp.max_team_size:
        raise HTTPException(409, "Team is full")

    existing = _get_member(db, team.id, actor.id)
    if existing and existing.status == TeamMemberStatus.accepted:
        raise HTTPException(409, "You are already a member of this team")

    if existing:
        existing.status = TeamMemberStatus.accepted
        existing.joined_at = datetime.utcnow()
        member = existing
    else:
        member = CompetitionTeamMember(
            team_id=team.id,
            user_id=actor.id,
            role=TeamMemberRole.member,
            status=TeamMemberStatus.accepted,
            joined_at=datetime.utcnow(),
        )
        db.add(member)

    _recompute_application(db, team)

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.join_by_code", target_type="team", target_id=team.id,
    )
    db.commit()
    db.refresh(member)
    return member


# ── Участники ────────────────────────────────────────────────────────

def kick_member(
    db: Session, comp: Competition, team: CompetitionTeam, user_id: int, actor: User,
) -> None:
    _ensure_captain(team, actor)
    if user_id == team.captain_id:
        raise HTTPException(400, "Captain cannot kick themselves; disband or transfer first")

    m = _get_member(db, team.id, user_id)
    if not m or m.status != TeamMemberStatus.accepted:
        raise HTTPException(404, "Member not found")

    m.status = TeamMemberStatus.removed
    _recompute_application(db, team)
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.kick", target_type="user", target_id=user_id,
    )
    db.commit()


def leave_team(
    db: Session, comp: Competition, team: CompetitionTeam, actor: User,
) -> None:
    if team.captain_id == actor.id:
        raise HTTPException(400, "Captain cannot leave; disband or transfer first")
    m = _get_member(db, team.id, actor.id)
    if not m or m.status != TeamMemberStatus.accepted:
        raise HTTPException(404, "You are not a member of this team")

    m.status = TeamMemberStatus.removed
    _recompute_application(db, team)
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="team.leave", target_type="team", target_id=team.id,
    )
    db.commit()


# ── Чтение ───────────────────────────────────────────────────────────

def list_teams(
    db: Session, comp: Competition, user: Optional[User],
) -> list[CompetitionTeam]:
    is_staff = user and _is_moderator_of(db, comp.id, user)
    if comp.public_team_roster or is_staff:
        return (
            db.query(CompetitionTeam)
            .filter_by(competition_id=comp.id)
            .order_by(CompetitionTeam.created_at)
            .all()
        )
    if not user:
        return []
    return (
        db.query(CompetitionTeam)
        .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status.in_(
                [TeamMemberStatus.accepted, TeamMemberStatus.invited]
            ),
        )
        .all()
    )


def get_my_team(
    db: Session, comp: Competition, user: User,
) -> Optional[CompetitionTeam]:
    return (
        db.query(CompetitionTeam)
        .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status == TeamMemberStatus.accepted,
        )
        .first()
    )


def list_my_invitations(
    db: Session, comp: Competition, user: User,
) -> list[CompetitionTeam]:
    return (
        db.query(CompetitionTeam)
        .join(CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id)
        .filter(
            CompetitionTeam.competition_id == comp.id,
            CompetitionTeamMember.user_id == user.id,
            CompetitionTeamMember.status == TeamMemberStatus.invited,
        )
        .all()
    )