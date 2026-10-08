"""Агрегаты для дашборда соревнования (только админ/модератор)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User
from ..models_competitions import (
    ApplicationStatus,
    Competition,
    CompetitionApplication,
    CompetitionChallenge,
    CompetitionScoreEvent,
    CompetitionSolve,
    CompetitionTeam,
    ScoreEventReason,
)
from . import competition_leaderboard_service as lb


@dataclass
class DashboardData:
    competition_id: int
    slug: str
    generated_at: datetime
    participants: dict[str, int] = field(default_factory=dict)
    challenges: dict[str, int] = field(default_factory=dict)
    solves: dict[str, int] = field(default_factory=dict)
    score_distribution: list[dict[str, Any]] = field(default_factory=list)
    solves_timeline: list[dict[str, Any]] = field(default_factory=list)
    first_bloods: list[dict[str, Any]] = field(default_factory=list)
    top_solvers: list[dict[str, Any]] = field(default_factory=list)
    category_activity: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)


def compute(db: Session, comp: Competition) -> DashboardData:
    data = DashboardData(
        competition_id=comp.id,
        slug=comp.slug,
        generated_at=datetime.utcnow(),
    )

    # ── Участники ──
    apps_by_status = (
        db.query(CompetitionApplication.status, func.count(CompetitionApplication.id))
        .filter(CompetitionApplication.competition_id == comp.id)
        .group_by(CompetitionApplication.status)
        .all()
    )
    for status, cnt in apps_by_status:
        key = status.value if hasattr(status, "value") else str(status)
        data.participants[key] = int(cnt)

    data.participants["teams_total"] = int(
        db.query(func.count(CompetitionTeam.id))
        .filter(CompetitionTeam.competition_id == comp.id)
        .scalar() or 0
    )

    # ── Задания ──
    data.challenges["total"] = int(
        db.query(func.count(CompetitionChallenge.id))
        .filter(CompetitionChallenge.competition_id == comp.id)
        .scalar() or 0
    )
    data.challenges["enabled"] = int(
        db.query(func.count(CompetitionChallenge.id))
        .filter(
            CompetitionChallenge.competition_id == comp.id,
            CompetitionChallenge.enabled.is_(True),
        )
        .scalar() or 0
    )
    data.challenges["built"] = int(
        db.query(func.count(CompetitionChallenge.id))
        .filter(
            CompetitionChallenge.competition_id == comp.id,
            CompetitionChallenge.build_status == "ready",
        )
        .scalar() or 0
    )

    # ── Решения ──
    data.solves["total"] = int(
        db.query(func.count(CompetitionSolve.id))
        .filter(CompetitionSolve.competition_id == comp.id)
        .scalar() or 0
    )
    data.solves["unique_users"] = int(
        db.query(func.count(func.distinct(CompetitionSolve.user_id)))
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.user_id.isnot(None),
        )
        .scalar() or 0
    )
    data.solves["unique_teams"] = int(
        db.query(func.count(func.distinct(CompetitionSolve.team_id)))
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.team_id.isnot(None),
        )
        .scalar() or 0
    )

    # ── Timeline решений (по часам) ──
    rows = (
        db.query(
            func.date_trunc("hour", CompetitionSolve.solved_at).label("bucket"),
            func.count(CompetitionSolve.id),
        )
        .filter(CompetitionSolve.competition_id == comp.id)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    data.solves_timeline = [
        {"t": bucket.isoformat() if bucket else None, "count": int(cnt)}
        for bucket, cnt in rows
    ]

    # ── First bloods ──
    fb = (
        db.query(CompetitionSolve)
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.is_first_blood.is_(True),
        )
        .order_by(CompetitionSolve.solved_at)
        .all()
    )
    ch_map = {
        cid: slug
        for cid, slug in (
            db.query(CompetitionChallenge.id, CompetitionChallenge.slug)
            .filter(CompetitionChallenge.competition_id == comp.id)
            .all()
        )
    }
    for s in fb:
        owner = _owner_name(db, s.user_id, s.team_id)
        data.first_bloods.append({
            "challenge": ch_map.get(s.challenge_id, str(s.challenge_id)),
            "owner": owner,
            "at": s.solved_at.isoformat(),
        })

    # ── Top solvers ──
    top_users = (
        db.query(
            CompetitionSolve.user_id,
            func.count(CompetitionSolve.id).label("cnt"),
        )
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.user_id.isnot(None),
        )
        .group_by(CompetitionSolve.user_id)
        .order_by(func.count(CompetitionSolve.id).desc())
        .limit(10)
        .all()
    )
    for uid, cnt in top_users:
        u = db.query(User).filter(User.id == uid).first()
        data.top_solvers.append({
            "user_id": uid,
            "username": u.username if u else "?",
            "solves": int(cnt),
        })

    # ── Активность по категориям ──
    cat_rows = (
        db.query(
            CompetitionChallenge.category,
            func.count(CompetitionSolve.id),
        )
        .join(CompetitionSolve, CompetitionSolve.challenge_id == CompetitionChallenge.id)
        .filter(CompetitionChallenge.competition_id == comp.id)
        .group_by(CompetitionChallenge.category)
        .all()
    )
    data.category_activity = [
        {"category": cat, "solves": int(cnt)}
        for cat, cnt in cat_rows
    ]

    # ── Score distribution ──
    snapshot = lb.compute(db, comp)
    data.score_distribution = [
        {"name": r.name, "score": r.score, "rank": r.rank}
        for r in snapshot.individuals[:20]
    ]

    # ── Аномалии ──
    data.anomalies = _detect_anomalies(db, comp)

    return data


def _owner_name(db: Session, user_id: Optional[int], team_id: Optional[int]) -> str:
    if team_id is not None:
        t = db.query(CompetitionTeam).filter(CompetitionTeam.id == team_id).first()
        return f"team:{t.name}" if t else f"team:{team_id}"
    if user_id is not None:
        u = db.query(User).filter(User.id == user_id).first()
        return u.username if u else f"user:{user_id}"
    return "?"


def _detect_anomalies(db: Session, comp: Competition) -> list[dict[str, Any]]:
    """Простые эвристики. Ничего не блокируют, только подсвечивают."""
    anomalies: list[dict[str, Any]] = []

    # 1. Решение быстрее 10 секунд после старта соревнования.
    if comp.starts_at:
        threshold = comp.starts_at + timedelta(seconds=10)
        fast = (
            db.query(CompetitionSolve)
            .filter(
                CompetitionSolve.competition_id == comp.id,
                CompetitionSolve.solved_at < threshold,
            )
            .all()
        )
        for s in fast:
            anomalies.append({
                "type": "fast_solve",
                "owner": _owner_name(db, s.user_id, s.team_id),
                "challenge_id": s.challenge_id,
                "at": s.solved_at.isoformat(),
            })

    # 2. Много hint_penalty без решений.
    hint_users = (
        db.query(
            CompetitionScoreEvent.user_id,
            func.count(CompetitionScoreEvent.id).label("cnt"),
        )
        .filter(
            CompetitionScoreEvent.competition_id == comp.id,
            CompetitionScoreEvent.reason == ScoreEventReason.hint_penalty,
            CompetitionScoreEvent.user_id.isnot(None),
        )
        .group_by(CompetitionScoreEvent.user_id)
        .having(func.count(CompetitionScoreEvent.id) >= 5)
        .all()
    )
    for uid, cnt in hint_users:
        solves = (
            db.query(func.count(CompetitionSolve.id))
            .filter(
                CompetitionSolve.competition_id == comp.id,
                CompetitionSolve.user_id == uid,
            )
            .scalar() or 0
        )
        if solves == 0:
            anomalies.append({
                "type": "hint_only",
                "user_id": uid,
                "hints": int(cnt),
                "solves": 0,
            })

    # 3. Резкий рост очков у одного участника (>50% от своего счёта за час).
    # Здесь упрощённо — не считаем.
    return anomalies