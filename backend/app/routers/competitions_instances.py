"""Роутер инстансов и submit для соревнований."""
import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..models_competitions import (
    ApplicationStatus,
    CompetitionApplication,
    CompetitionChallengeHintPurchase,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
    TeamMemberStatus,
    TeamStatus,
)
from ..schemas_competitions import (
    CompetitionInstanceOut,
    CompetitionFlagSubmit,
    CompetitionSubmitResult,
    HintPurchaseOut,
)
from ..security import get_current_user
from ..services import (
    competition_challenge_service as cc_service,
    competition_instance_service as ci_service,
    competition_scoring_service as cs_service,
    competition_service,
)


router = APIRouter(prefix="/competitions", tags=["competitions:instances"])


def _client_host(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        forwarded = forwarded.split(",")[0].strip()
    host = forwarded or request.headers.get("host", "")
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host or settings.public_host


def _user_team_id(db: Session, comp, user: User) -> Optional[int]:
    t = (
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
    return t.id if t else None


# ── Start / stop ─────────────────────────────────────────────────────

@router.post(
    "/{slug}/challenges/{ch_slug}/start",
    response_model=CompetitionInstanceOut,
)
def start_challenge(
    slug: str,
    ch_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    instance = ci_service.start(db, comp, ch, user)

    host = _client_host(request)
    url = f"http://{host}:{instance.host_port}"
    return CompetitionInstanceOut(
        challenge_slug=ch.slug,
        url=url,
        expires_at=instance.expires_at,
    )


@router.post("/{slug}/challenges/{ch_slug}/stop")
def stop_challenge(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)
    ci_service.stop(db, comp, ch, user)
    return {"status": "stopped"}


# ── Submit ───────────────────────────────────────────────────────────

@router.post(
    "/{slug}/challenges/{ch_slug}/submit",
    response_model=CompetitionSubmitResult,
)
def submit_flag(
    slug: str,
    ch_slug: str,
    payload: CompetitionFlagSubmit,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)

    if comp.status not in (CompetitionStatus.running, CompetitionStatus.paused):
        raise HTTPException(409, "Competition is not running")

    team_id = _user_team_id(db, comp, user)
    # Проверка участия
    if user.role.value not in ("admin", "moderator"):
        if team_id is not None:
            app = (
                db.query(CompetitionApplication)
                .filter_by(competition_id=comp.id, team_id=team_id)
                .first()
            )
            if not app or app.status != ApplicationStatus.approved:
                raise HTTPException(403, "Team is not approved")
        else:
            app = (
                db.query(CompetitionApplication)
                .filter_by(competition_id=comp.id, user_id=user.id)
                .first()
            )
            if not app or app.status != ApplicationStatus.approved:
                raise HTTPException(403, "You are not approved for this competition")

    # Уже решено?
    if cc_service.is_solved_by(db, ch, user_id=user.id, team_id=team_id):
        return CompetitionSubmitResult(
            correct=True, message="Уже решено ранее", points_awarded=0,
        )

    submitted_hash = hashlib.sha256(payload.flag.strip().encode("utf-8")).hexdigest()

    # Проверка динамического флага
    strategy = (
        ch.dynamic_flag_strategy.value
        if hasattr(ch.dynamic_flag_strategy, "value")
        else str(ch.dynamic_flag_strategy)
    )
    is_correct = False
    if strategy == "static":
        is_correct = submitted_hash == ch.flag_hash
    else:
        # Для динамических — сверяемся с hash инстанса пользователя/команды.
        from ..models import ChallengeInstance
        q = (
            db.query(ChallengeInstance)
            .filter_by(competition_id=comp.id, challenge_id=ch.id)
            .filter(ChallengeInstance.status == "running")
        )
        if team_id is not None:
            q = q.filter_by(team_id=team_id)
        else:
            q = q.filter_by(user_id=user.id)
        instance = q.first()
        if instance and instance.dynamic_flag_hash:
            is_correct = submitted_hash == instance.dynamic_flag_hash
        # Также принимаем оригинальный ch.flag_hash (для случая, когда
        # админ настраивает статический флаг даже при strategy != static).
        if not is_correct:
            is_correct = submitted_hash == ch.flag_hash

    if not is_correct:
        return CompetitionSubmitResult(correct=False, message="Неверный флаг")

    solve = cs_service.record_solve(
        db, comp, ch,
        user_id=user.id if team_id is None else None,
        team_id=team_id,
        flag_used_hash=submitted_hash,
    )

    # Автостоп
    try:
        from ..models import ChallengeInstance
        from ..services import orchestrator
        q = (
            db.query(ChallengeInstance)
            .filter_by(
                competition_id=comp.id, challenge_id=ch.id, status="running",
            )
        )
        if team_id is not None:
            q = q.filter_by(team_id=team_id)
        else:
            q = q.filter_by(user_id=user.id)
        inst = q.first()
        if inst:
            orchestrator.stop_competition_instance(db, inst)
    except Exception:
        pass

    return CompetitionSubmitResult(
        correct=True,
        message=f"Флаг верный! +{solve.points_awarded} очков",
        points_awarded=solve.points_awarded,
        is_first_blood=solve.is_first_blood,
    )


# ── Подсказки ────────────────────────────────────────────────────────

@router.post(
    "/{slug}/challenges/{ch_slug}/hints/{hint_index}/buy",
    response_model=HintPurchaseOut,
)
def buy_hint(
    slug: str,
    ch_slug: str,
    hint_index: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)

    hints = ch.hints_json or []
    if hint_index < 0 or hint_index >= len(hints):
        raise HTTPException(404, "Hint not found")

    team_id = _user_team_id(db, comp, user)
    hint = hints[hint_index]
    cost = int(hint.get("cost", 0))

    # Проверка: не куплена ли уже
    q = db.query(CompetitionChallengeHintPurchase).filter_by(
        challenge_id=ch.id, hint_index=hint_index,
    )
    if team_id is not None:
        q = q.filter_by(team_id=team_id)
    else:
        q = q.filter_by(user_id=user.id)
    if q.first():
        raise HTTPException(409, "Hint already purchased")

    if cost > 0:
        cs_service.charge_hint(
            db, comp, ch,
            user_id=user.id if team_id is None else None,
            team_id=team_id,
            cost=cost,
        )

    purchase = CompetitionChallengeHintPurchase(
        competition_id=comp.id,
        challenge_id=ch.id,
        user_id=user.id if team_id is None else None,
        team_id=team_id,
        hint_index=hint_index,
        cost_paid=cost,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)

    return HintPurchaseOut(
        hint_index=hint_index,
        text=hint.get("text", ""),
        cost_paid=cost,
        purchased_at=purchase.purchased_at,
    )


@router.get(
    "/{slug}/challenges/{ch_slug}/hints/purchased",
    response_model=list[HintPurchaseOut],
)
def list_purchased_hints(
    slug: str,
    ch_slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = competition_service.get_by_slug(db, slug)
    ch = cc_service.get_challenge(db, comp, ch_slug)

    team_id = _user_team_id(db, comp, user)
    q = db.query(CompetitionChallengeHintPurchase).filter_by(challenge_id=ch.id)
    if team_id is not None:
        q = q.filter_by(team_id=team_id)
    else:
        q = q.filter_by(user_id=user.id)
    rows = q.order_by(CompetitionChallengeHintPurchase.hint_index).all()

    hints = ch.hints_json or []
    out = []
    for p in rows:
        text = ""
        if 0 <= p.hint_index < len(hints):
            text = hints[p.hint_index].get("text", "")
        out.append(HintPurchaseOut(
            hint_index=p.hint_index,
            text=text,
            cost_paid=p.cost_paid,
            purchased_at=p.purchased_at,
        ))
    return out