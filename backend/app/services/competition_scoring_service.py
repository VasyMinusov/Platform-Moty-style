"""Начисление очков в соревновании.

Режимы:
- fixed          — все получают points из scoring_config.default_points
                   (или ch.points, если default не задан)
- dynamic_decay  — первое решение max_points, дальше по формуле
- placement      — очки раздаются при finish по местам (не на solve)

Штрафы за подсказки — hint_penalty.
Бонусы (first_blood, all_category) — bonus.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models_competitions import (
    Competition,
    CompetitionChallenge,
    CompetitionSolve,
    CompetitionScoreEvent,
    ScoreEventReason,
)


def compute_solve_points(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    *,
    prior_solves: int,
) -> int:
    """Считает очки за решение.

    prior_solves — сколько решений этого задания уже было ДО текущего
    (0 для первого).
    """
    cfg = comp.scoring_config or {}
    mode = cfg.get("mode", "fixed")

    # per-challenge override
    overrides = cfg.get("per_challenge_override", {})
    override = overrides.get(ch.slug)
    if override:
        mode = override.get("mode", mode)
        if mode == "fixed" and override.get("points") is not None:
            return int(override["points"])

    if mode == "fixed":
        default = cfg.get("default_points")
        if default is not None:
            return int(default)
        return int(ch.points)

    if mode == "dynamic_decay":
        dd = cfg.get("dynamic_decay", {})
        decay_type = dd.get("decay_type", "step")
        decay_step = int(dd.get("decay_step", 5))
        decay_interval = int(dd.get("decay_interval", 5))
        min_points = int(dd.get("min_points", 50))
        max_points = int(dd.get("max_points", 1000))

        if decay_type == "step":
            steps = prior_solves // max(decay_interval, 1)
            pts = max_points - steps * decay_step
        elif decay_type == "linear":
            span = max(1, decay_interval * 10)
            pts = max_points - int((max_points - min_points) * prior_solves / span)
        elif decay_type == "logarithmic":
            import math
            pts = max_points - int(math.log2(prior_solves + 1) * decay_step)
        else:
            pts = max_points

        return max(min_points, min(max_points, pts))

    if mode == "placement":
        # Очки за решение не начисляются; плейсменты раздаются при finish.
        return 0

    return int(ch.points)


def record_solve(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    *,
    user_id: int | None,
    team_id: int | None,
    flag_used_hash: str,
) -> CompetitionSolve:
    """Записывает решение, начисляет очки, шлёт score event."""
    # Сколько решений уже было?
    prior = (
        db.query(func.count(CompetitionSolve.id))
        .filter(CompetitionSolve.challenge_id == ch.id)
        .scalar()
        or 0
    )
    is_first_blood = prior == 0

    points = compute_solve_points(db, comp, ch, prior_solves=prior)

    solve = CompetitionSolve(
        competition_id=comp.id,
        challenge_id=ch.id,
        user_id=user_id,
        team_id=team_id,
        points_awarded=points,
        rank_at_solve=prior + 1,
        flag_used_hash=flag_used_hash,
        is_first_blood=is_first_blood,
    )
    db.add(solve)
    db.flush()

    if points != 0:
        db.add(CompetitionScoreEvent(
            competition_id=comp.id,
            user_id=user_id,
            team_id=team_id,
            delta=points,
            reason=ScoreEventReason.solve,
            related_id=solve.id,
        ))

    # Бонусы
    cfg = comp.scoring_config or {}
    for bonus in cfg.get("bonuses", []):
        btype = bonus.get("type")
        bpts = int(bonus.get("points", 0))
        if bpts <= 0:
            continue
        if btype == "first_blood" and is_first_blood:
            db.add(CompetitionScoreEvent(
                competition_id=comp.id,
                user_id=user_id,
                team_id=team_id,
                delta=bpts,
                reason=ScoreEventReason.bonus,
                related_id=solve.id,
            ))
        elif btype == "all_category":
            cat = bonus.get("category")
            if cat and ch.category == cat:
                total_in_cat = (
                    db.query(func.count(CompetitionChallenge.id))
                    .filter(
                        CompetitionChallenge.competition_id == comp.id,
                        CompetitionChallenge.category == cat,
                        CompetitionChallenge.enabled.is_(True),
                    )
                    .scalar()
                    or 0
                )
                solved_in_cat = (
                    db.query(func.count(func.distinct(CompetitionSolve.challenge_id)))
                    .join(CompetitionChallenge, CompetitionChallenge.id == CompetitionSolve.challenge_id)
                    .filter(
                        CompetitionSolve.competition_id == comp.id,
                        CompetitionChallenge.category == cat,
                    )
                    .filter(
                        (CompetitionSolve.user_id == user_id)
                        if team_id is None
                        else (CompetitionSolve.team_id == team_id)
                    )
                    .scalar()
                    or 0
                )
                if total_in_cat > 0 and solved_in_cat >= total_in_cat:
                    db.add(CompetitionScoreEvent(
                        competition_id=comp.id,
                        user_id=user_id,
                        team_id=team_id,
                        delta=bpts,
                        reason=ScoreEventReason.bonus,
                        related_id=solve.id,
                    ))

    db.commit()
    db.refresh(solve)

    # ── Публикация в WebSocket-канал соревнования (пункт 11) ──
    # Импорт локальный, чтобы не тянуть FastAPI/asyncio на уровне модуля
    # (это позволяет competition_scoring_service оставаться синхронным).
    try:
        from .competition_stream import publish_sync
        publish_sync(f"comp:{comp.slug}", {
            "type": "solve.created",
            "data": {
                "challenge_slug": ch.slug,
                "user_id": user_id,
                "team_id": team_id,
                "points": solve.points_awarded,
                "is_first_blood": solve.is_first_blood,
            },
        })
    except Exception:
        # Если WebSocket-хаб недоступен — не валим submit.
        pass

    return solve


def charge_hint(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    *,
    user_id: int | None,
    team_id: int | None,
    cost: int,
) -> None:
    if cost <= 0:
        return
    db.add(CompetitionScoreEvent(
        competition_id=comp.id,
        user_id=user_id,
        team_id=team_id,
        delta=-cost,
        reason=ScoreEventReason.hint_penalty,
    ))


def total_score(
    db: Session, comp: Competition, *, user_id: int | None, team_id: int | None,
) -> int:
    q = (
        db.query(func.coalesce(func.sum(CompetitionScoreEvent.delta), 0))
        .filter(CompetitionScoreEvent.competition_id == comp.id)
    )
    if team_id is not None:
        q = q.filter(CompetitionScoreEvent.team_id == team_id)
    else:
        q = q.filter(CompetitionScoreEvent.user_id == user_id)
    return int(q.scalar() or 0)