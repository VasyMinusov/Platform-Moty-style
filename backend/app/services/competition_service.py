"""Бизнес-логика соревнований.

Здесь: CRUD, статус-машина, права, аудит. Всё, что не связано с Docker и
заданиями, живёт здесь. Задания и инстансы — в следующих фазах.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User, UserRole
from ..models_competitions import (
    ApplicationStatus, Competition, CompetitionApplication, CompetitionModerator,
    CompetitionStatus, ModeratorRole,
)
from ..schemas_competitions import (
    ApplicationDecision, CompetitionCreate, CompetitionUpdate,
    ModeratorAdd, ScoringConfig,
)
from . import competition_audit, competition_network, competition_ports


# ── Разрешённые переходы статусов ─────────────────────────────────────
# Ключ — текущий статус, значение — множество допустимых следующих.
TRANSITIONS: dict[CompetitionStatus, set[CompetitionStatus]] = {
    CompetitionStatus.draft: {CompetitionStatus.announced, CompetitionStatus.cancelled},
    CompetitionStatus.announced: {
        CompetitionStatus.registration_open,
        CompetitionStatus.cancelled,
        CompetitionStatus.draft,  # откат, пока не открыли регистрацию
    },
    CompetitionStatus.registration_open: {
        CompetitionStatus.registration_closed,
        CompetitionStatus.cancelled,
    },
    CompetitionStatus.registration_closed: {
        CompetitionStatus.running,
        CompetitionStatus.cancelled,
    },
    CompetitionStatus.running: {
        CompetitionStatus.paused,
        CompetitionStatus.finished,
        CompetitionStatus.cancelled,
    },
    CompetitionStatus.paused: {
        CompetitionStatus.running,
        CompetitionStatus.finished,
        CompetitionStatus.cancelled,
    },
    CompetitionStatus.finished: set(),
    CompetitionStatus.cancelled: set(),
}


# Статусы, в которых разрешено менять «тяжёлые» поля (расписание, режим,
# scoring, сеть). После старта — только через отдельные endpoint'ы.
EDITABLE_STATUSES = {
    CompetitionStatus.draft,
    CompetitionStatus.announced,
    CompetitionStatus.registration_open,
    CompetitionStatus.registration_closed,
}


# ── CRUD ──────────────────────────────────────────────────────────────

def list_competitions(
    db: Session,
    *,
    user: Optional[User],
    status: Optional[str] = None,
    visibility: Optional[str] = None,
    only_mine: bool = False,
    include_hidden: bool = False,
) -> list[Competition]:
    q = db.query(Competition).filter(Competition.deleted_at.is_(None))

    if status:
        q = q.filter(Competition.status == status)
    if visibility:
        q = q.filter(Competition.visibility == visibility)

    if only_mine and user:
        q = q.filter(Competition.created_by == user.id)

    # Скрытые и приватные — только админ/модератор/участник
    if not include_hidden and (user is None or user.role == UserRole.student):
        q = q.filter(Competition.visibility == "public")

    return q.order_by(Competition.starts_at.desc().nullslast(), Competition.id.desc()).all()


def get_by_slug(db: Session, slug: str) -> Competition:
    c = (
        db.query(Competition)
        .filter(Competition.slug == slug, Competition.deleted_at.is_(None))
        .first()
    )
    if not c:
        raise HTTPException(404, "Competition not found")
    return c


def create_competition(db: Session, payload: CompetitionCreate, author: User) -> Competition:
    if db.query(Competition).filter(Competition.slug == payload.slug).first():
        raise HTTPException(409, "Competition with this slug already exists")

    c = Competition(
        slug=payload.slug,
        title=payload.title,
        summary=payload.summary,
        description_md=payload.description_md,
        rules_md=payload.rules_md,
        visibility=payload.visibility,
        mode=payload.mode,
        status=CompetitionStatus.draft,
        registration_opens_at=payload.registration_opens_at,
        registration_closes_at=payload.registration_closes_at,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        allow_late_application=payload.allow_late_application,
        allow_late_withdraw=payload.allow_late_withdraw,
        max_participants=payload.max_participants,
        max_teams=payload.max_teams,
        min_team_size=payload.min_team_size,
        max_team_size=payload.max_team_size,
        public_team_roster=payload.public_team_roster,
        leaderboard_visibility=payload.leaderboard_visibility,
        tie_breaker=payload.tie_breaker,
        scoring_config=payload.scoring_config.model_dump(),
        network_config=payload.network_config.model_dump(),
        instance_ttl_seconds=payload.instance_ttl_seconds,
        max_instances_per_user=payload.max_instances_per_user,
        max_instances_per_team=payload.max_instances_per_team,
        max_instances_per_competition=payload.max_instances_per_competition,
        created_by=author.id,
    )
    db.add(c)
    db.flush()  # получить c.id

    # Создатель-модератор автоматически становится ответственным, чтобы
    # мог вести соревнование до назначения других.
    db.add(CompetitionModerator(
        competition_id=c.id,
        user_id=author.id,
        role=ModeratorRole.responsible,
        added_by=author.id,
    ))

    competition_audit.log_action(
        db,
        competition_id=c.id,
        actor=author,
        action="competition.create",
        payload={"slug": c.slug, "title": c.title},
    )
    db.commit()
    db.refresh(c)
    return c


def update_competition(
    db: Session, c: Competition, payload: CompetitionUpdate, actor: User,
) -> Competition:
    if c.status not in EDITABLE_STATUSES:
        raise HTTPException(
            409,
            f"Cannot edit competition in status={c.status.value}. "
            f"Use dedicated endpoints (pause/resume/finish) instead.",
        )

    data = payload.model_dump(exclude_unset=True)
    changed: dict = {}

    for field, value in data.items():
        if field == "scoring_config" and value is not None:
            value = ScoringConfig.model_validate(value).model_dump()
        if field == "network_config" and value is not None:
            value = value  # уже dict после exclude_unset
        setattr(c, field, value)
        changed[field] = value

    if changed:
        c.updated_at = datetime.utcnow()

    competition_audit.log_action(
        db,
        competition_id=c.id,
        actor=actor,
        action="competition.update",
        payload={"changed": list(changed.keys())},
    )
    db.commit()
    db.refresh(c)
    return c


# ── Переходы статусов ─────────────────────────────────────────────────

def _ensure_transition(c: Competition, target: CompetitionStatus):
    if target not in TRANSITIONS.get(c.status, set()):
        raise HTTPException(
            409,
            f"Transition {c.status.value} -> {target.value} is not allowed",
        )


def transition_status(
    db: Session, c: Competition, target: CompetitionStatus, actor: User, *,
    reason: Optional[str] = None,
) -> Competition:
    _ensure_transition(c, target)

    old = c.status
    c.status = target
    c.updated_at = datetime.utcnow()

    # Побочные эффекты
    if target == CompetitionStatus.announced:
        # Выделяем диапазон портов и создаём Docker-сеть.
        try:
            competition_ports.allocate_port_range(db, c)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        try:
            competition_network.ensure_network(c)
        except Exception as e:
            # Не откатываем статус — публикация всё равно полезна, сеть
            # создастся при первом запуске инстанса.
            competition_audit.log_action(
                db, competition_id=c.id, actor=actor,
                action="competition.network_warning",
                payload={"error": str(e)},
            )

    if target in (CompetitionStatus.finished, CompetitionStatus.cancelled):
        # Останавливаем все инстансы соревнования.
        from . import orchestrator
        stopped = orchestrator.stop_all_for_competition(db, c.id)
        competition_audit.log_action(
            db, competition_id=c.id, actor=actor,
            action="competition.instances_reaped",
            payload={"stopped": stopped},
        )

    competition_audit.log_action(
        db,
        competition_id=c.id,
        actor=actor,
        action="competition.status",
        payload={"from": old.value, "to": target.value, "reason": reason},
    )
    db.commit()
    db.refresh(c)
    return c


def soft_delete(db: Session, c: Competition, actor: User) -> None:
    if c.status not in (CompetitionStatus.draft, CompetitionStatus.announced, CompetitionStatus.cancelled):
        raise HTTPException(409, "Only draft/announced/cancelled competitions can be deleted")
    c.deleted_at = datetime.utcnow()
    competition_audit.log_action(
        db, competition_id=c.id, actor=actor, action="competition.delete",
    )
    db.commit()


# ── Модераторы ────────────────────────────────────────────────────────

def add_moderator(db: Session, c: Competition, payload: ModeratorAdd, actor: User) -> CompetitionModerator:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role not in (UserRole.moderator, UserRole.admin):
        raise HTTPException(400, "Only moderators and admins can be assigned")

    existing = (
        db.query(CompetitionModerator)
        .filter_by(competition_id=c.id, user_id=payload.user_id)
        .first()
    )
    if existing:
        raise HTTPException(409, "User is already a moderator of this competition")

    m = CompetitionModerator(
        competition_id=c.id,
        user_id=payload.user_id,
        role=ModeratorRole(payload.role),
        added_by=actor.id,
    )
    db.add(m)
    competition_audit.log_action(
        db, competition_id=c.id, actor=actor,
        action="competition.moderator.add",
        target_type="user", target_id=user.id,
        payload={"role": payload.role},
    )
    db.commit()
    db.refresh(m)
    return m


def remove_moderator(db: Session, c: Competition, user_id: int, actor: User) -> None:
    m = (
        db.query(CompetitionModerator)
        .filter_by(competition_id=c.id, user_id=user_id)
        .first()
    )
    if not m:
        raise HTTPException(404, "Moderator not found")
    if m.user_id == c.created_by:
        raise HTTPException(400, "Cannot remove the creator")
    db.delete(m)
    competition_audit.log_action(
        db, competition_id=c.id, actor=actor,
        action="competition.moderator.remove",
        target_type="user", target_id=user_id,
    )
    db.commit()


def list_moderators(db: Session, c: Competition) -> list[CompetitionModerator]:
    return (
        db.query(CompetitionModerator)
        .filter_by(competition_id=c.id)
        .all()
    )


# ── Права ─────────────────────────────────────────────────────────────

def can_view(db: Session, c: Competition, user: Optional[User]) -> bool:
    if user and user.role == UserRole.admin:
        return True
    if c.visibility == "public":
        return True
    if not user:
        return False
    # Приватное/скрытое: модератор соревнования или подавший заявку.
    m = (
        db.query(CompetitionModerator)
        .filter_by(competition_id=c.id, user_id=user.id)
        .first()
    )
    if m:
        return True
    a = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=c.id, user_id=user.id)
        .first()
    )
    return a is not None


# ── Публикация заявок ─────────────────────────────────────────────────

def apply_to_competition(
    db: Session, c: Competition, user: User, motivation: Optional[str], comment: Optional[str],
) -> CompetitionApplication:
    if c.status not in (CompetitionStatus.registration_open,):
        raise HTTPException(409, "Registration is not open")
    if c.registration_closes_at and datetime.utcnow() > c.registration_closes_at \
            and not c.allow_late_application:
        raise HTTPException(409, "Registration is closed")

    if db.query(CompetitionApplication).filter_by(competition_id=c.id, user_id=user.id).first():
        raise HTTPException(409, "You have already applied")

    # Лимит участников
    if c.max_participants is not None:
        approved = (
            db.query(func.count(CompetitionApplication.id))
            .filter_by(competition_id=c.id, status=ApplicationStatus.approved)
            .scalar()
        )
        if approved >= c.max_participants:
            raise HTTPException(409, "Competition is full")

    a = CompetitionApplication(
        competition_id=c.id,
        user_id=user.id,
        motivation=motivation,
        comment=comment,
        status=ApplicationStatus.pending,
    )
    db.add(a)
    competition_audit.log_action(
        db, competition_id=c.id, actor=user,
        action="application.create", target_type="user", target_id=user.id,
    )
    db.commit()
    db.refresh(a)
    return a


def withdraw_application(db: Session, c: Competition, user: User) -> CompetitionApplication:
    a = db.query(CompetitionApplication).filter_by(competition_id=c.id, user_id=user.id).first()
    if not a:
        raise HTTPException(404, "Application not found")
    if a.status in (ApplicationStatus.withdrawn, ApplicationStatus.rejected):
        raise HTTPException(409, "Application is not active")
    if c.status not in EDITABLE_STATUSES and not c.allow_late_withdraw:
        raise HTTPException(409, "Withdraw is not allowed at this stage")

    a.status = ApplicationStatus.withdrawn
    a.decided_at = datetime.utcnow()
    competition_audit.log_action(
        db, competition_id=c.id, actor=user,
        action="application.withdraw", target_id=a.id,
    )
    db.commit()
    db.refresh(a)
    return a


def decide_application(
    db: Session, c: Competition, application_id: int,
    decision: ApplicationDecision, actor: User,
) -> CompetitionApplication:
    a = (
        db.query(CompetitionApplication)
        .filter_by(id=application_id, competition_id=c.id)
        .first()
    )
    if not a:
        raise HTTPException(404, "Application not found")
    if a.status in (ApplicationStatus.withdrawn,):
        raise HTTPException(409, "Application is withdrawn")

    a.status = ApplicationStatus(decision.status)
    a.decided_at = datetime.utcnow()
    a.decided_by = actor.id
    a.decision_comment = decision.comment

    competition_audit.log_action(
        db, competition_id=c.id, actor=actor,
        action="application.decide",
        target_type="application", target_id=a.id,
        payload={"status": a.status.value, "comment": decision.comment},
    )
    db.commit()
    db.refresh(a)

    # ── Уведомление участнику ─────────────────────────────────────────
    from . import notification_service

    link = f"/competitions/{c.slug}"
    if a.status == ApplicationStatus.approved:
        notification_service.push(
            db, user_id=a.user_id,
            type="application.approved",
            title="Заявка одобрена",
            message=c.title,
            level="success",
            link=link,
            payload={"competition_id": c.id, "application_id": a.id},
        )
    elif a.status == ApplicationStatus.rejected:
        notification_service.push(
            db, user_id=a.user_id,
            type="application.rejected",
            title="Заявка отклонена",
            message=c.title + (f" · {a.decision_comment}" if a.decision_comment else ""),
            level="danger",
            link=link,
            payload={
                "competition_id": c.id,
                "application_id": a.id,
                "comment": a.decision_comment,
            },
        )
    elif a.status == ApplicationStatus.waitlist:
        notification_service.push(
            db, user_id=a.user_id,
            type="application.waitlist",
            title="Заявка в листе ожидания",
            message=c.title,
            level="warning",
            link=link,
            payload={"competition_id": c.id, "application_id": a.id},
        )

    return a


def list_applications(
    db: Session, c: Competition, status: Optional[str] = None,
) -> list[CompetitionApplication]:
    q = db.query(CompetitionApplication).filter_by(competition_id=c.id)
    if status:
        q = q.filter(CompetitionApplication.status == status)
    return q.order_by(CompetitionApplication.applied_at.desc()).all()