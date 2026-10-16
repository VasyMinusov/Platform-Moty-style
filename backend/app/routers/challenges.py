import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Challenge, ChallengeInstance, Solve, User
from ..schemas import (
    ChallengeOut,
    FlagSubmit,
    InstanceDetailOut,
    InstanceOut,
    SubmitResult,
)
from ..security import get_current_user
from ..services import orchestrator

from ..config import settings
from ..database import get_db
from ..models import Challenge, ChallengeInstance, Solve, User
from ..schemas import (
    ChallengeOut,
    FlagSubmit,
    InstanceDetailOut,
    InstanceOut,
    SubmitResult,
)
from ..security import get_current_user
from ..services import orchestrator
router = APIRouter(prefix="/challenges", tags=["challenges"])


def _client_host(request: Request) -> str:
    """Возвращает хост, по которому клиент достучался до платформы,
    без порта. Учитывает X-Forwarded-Host (Vite dev / nginx / любой
    реверс-прокси) с fallback на стандартный Host.

    Это позволяет работать одновременно по нескольким адресам:
    Wi-Fi (192.168.135.120) и LAN за роутером (192.168.0.1) — URL
    инстансов будут формироваться относительно того адреса, который
    использовал конкретный клиент.
    """
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        # Может быть список через запятую — берём первый (самый внешний).
        forwarded = forwarded.split(",")[0].strip()
    host = forwarded or request.headers.get("host", "")
    # Отрезаем порт, если он есть: "192.168.0.1:5173" → "192.168.0.1".
    # IPv6 в квадратных скобках: "[::1]:5173" → "[::1]".
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host or settings.public_host


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


@router.get("/instances/running", response_model=list[InstanceDetailOut])
def list_my_running_instances(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InstanceDetailOut]:
    """
    Список running-инстансов ТЕКУЩЕГО пользователя для глобальных заданий.

    Нужен фронту, чтобы при возврате на /challenges показать «инстанс
    уже запущен», а не кнопку «Запустить». Состояние живёт на бэке
    (ChallengeInstance в БД), а не в React-компоненте.

    Возвращаются только инстансы БЕЗ competition_id — соревновательные
    отдаются через /competitions/{slug}/challenges (см.
    competitions_instances.py).

    URL формируется для того хоста, по которому клиент пришёл
    (X-Forwarded-Host / Host). Это позволяет работать одновременно
    по Wi-Fi и LAN-адресу.
    """
    rows = (
        db.query(ChallengeInstance, Challenge)
        .join(Challenge, Challenge.id == ChallengeInstance.challenge_id)
        .filter(
            ChallengeInstance.user_id == user.id,
            ChallengeInstance.status == "running",
            ChallengeInstance.competition_id.is_(None),
        )
        .order_by(ChallengeInstance.started_at.desc())
        .all()
    )

    host = _client_host(request)
    now = datetime.utcnow()

    return [
        InstanceDetailOut(
            id=inst.id,
            scope="global",
            user_id=user.id,
            username=user.username,
            challenge_id=ch.id,
            challenge_slug=ch.slug,
            challenge_title=ch.title,
            container_id=inst.container_id,
            host_port=inst.host_port,
            url=f"http://{host}:{inst.host_port}",
            status=inst.status,
            started_at=inst.started_at,
            expires_at=inst.expires_at,
            is_expired=inst.expires_at < now,
        )
        for inst, ch in rows
    ]


@router.post("/{slug}/start", response_model=InstanceOut)
def start_challenge(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.query(Challenge).filter_by(slug=slug, enabled=True).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")

    instance = orchestrator.start_instance(db, user.id, challenge)
    host = _client_host(request)
    url = f"http://{host}:{instance.host_port}"
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
            pass

    return SubmitResult(correct=True, message="Флаг верный! Инстанс остановлен.", points_awarded=challenge.points)
