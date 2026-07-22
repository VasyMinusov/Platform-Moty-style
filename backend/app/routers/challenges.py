import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Challenge, ChallengeInstance, Solve, User
from ..schemas import ChallengeOut, InstanceOut, FlagSubmit, SubmitResult
from ..security import get_current_user
from ..services import orchestrator

router = APIRouter(prefix="/challenges", tags=["challenges"])


@router.get("", response_model=list[ChallengeOut])
def list_challenges(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    solved_ids = {s.challenge_id for s in user.solves}
    challenges = db.query(Challenge).filter(Challenge.enabled.is_(True)).all()
    out = []
    for c in challenges:
        item = ChallengeOut.model_validate(c)
        item.solved = c.id in solved_ids
        out.append(item)
    return out


@router.post("/{slug}/start", response_model=InstanceOut)
def start_challenge(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    challenge = db.query(Challenge).filter_by(slug=slug, enabled=True).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")

    instance = orchestrator.start_instance(db, user.id, challenge)
    url = f"http://{settings.public_host}:{instance.host_port}"
    return InstanceOut(challenge_slug=slug, url=url, expires_at=instance.expires_at)


@router.post("/{slug}/stop")
def stop_challenge(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    challenge = db.query(Challenge).filter_by(slug=slug).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")

    instance = (
        db.query(ChallengeInstance)
        .filter_by(user_id=user.id, challenge_id=challenge.id, status="running")
        .first()
    )
    if not instance:
        raise HTTPException(404, "No running instance")

    orchestrator.stop_instance(db, instance)
    return {"status": "stopped"}


@router.post("/{slug}/submit", response_model=SubmitResult)
def submit_flag(slug: str, payload: FlagSubmit, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    challenge = db.query(Challenge).filter_by(slug=slug, enabled=True).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")

    already_solved = db.query(Solve).filter_by(user_id=user.id, challenge_id=challenge.id).first()
    if already_solved:
        return SubmitResult(correct=True, message="Уже решено ранее", points_awarded=0)

    submitted_hash = hashlib.sha256(payload.flag.strip().encode("utf-8")).hexdigest()
    if submitted_hash != challenge.flag_hash:
        return SubmitResult(correct=False, message="Неверный флаг")

    solve = Solve(user_id=user.id, challenge_id=challenge.id)
    db.add(solve)
    user.points += challenge.points
    db.commit()

    # ── АВТООСТАНОВКА: после верного флага останавливаем контейнер ──
    instance = (
        db.query(ChallengeInstance)
        .filter_by(user_id=user.id, challenge_id=challenge.id, status="running")
        .first()
    )
    if instance:
        try:
            orchestrator.stop_instance(db, instance)
        except Exception:
            # Не ломаем ответ пользователю, если остановка не удалась
            pass

    return SubmitResult(correct=True, message="Флаг верный! Инстанс остановлен.", points_awarded=challenge.points)