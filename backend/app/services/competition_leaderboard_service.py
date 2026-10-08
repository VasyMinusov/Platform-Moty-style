"""Расчёт лидерборда соревнования.

Поддерживает:
- individual — ранжируются пользователи
- team       — ранжируются команды
- both       — оба режима, отдельные таблицы

Tie-breaker:
- last_solve_time  — у кого последнее решение раньше
- first_solve_time — у кого первое решение раньше
- solves_count     — у кого больше решённых заданий
- alphabetic       — по алфавиту (имя пользователя/команды)

Очки берутся как сумма CompetitionScoreEvent.delta. Если событий ещё нет,
но есть решения с points_awarded — считаем по ним (fallback для старых данных).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User
from ..models_competitions import (
    Competition,
    CompetitionScoreEvent,
    CompetitionSolve,
    CompetitionTeam,
    CompetitionTeamMember,
    CompetitionMode,
    TeamMemberStatus,
    TieBreaker,
)


@dataclass
class LeaderboardRow:
    rank: int = 0
    id: int = 0
    name: str = ""
    score: int = 0
    solves_count: int = 0
    last_solve_at: Optional[datetime] = None
    first_solve_at: Optional[datetime] = None
    is_team: bool = False
    members: list[str] = field(default_factory=list)
    # Для отображения «прогресса по заданиям»
    solved_challenges: dict[str, datetime] = field(default_factory=dict)


@dataclass
class LeaderboardSnapshot:
    competition_id: int
    competition_slug: str
    mode: str
    generated_at: datetime
    individuals: list[LeaderboardRow]
    teams: list[LeaderboardRow]


# ── Вспомогательные ──────────────────────────────────────────────────

def _user_scores(db: Session, comp: Competition) -> dict[int, int]:
    rows = (
        db.query(
            CompetitionScoreEvent.user_id,
            func.coalesce(func.sum(CompetitionScoreEvent.delta), 0),
        )
        .filter(
            CompetitionScoreEvent.competition_id == comp.id,
            CompetitionScoreEvent.user_id.isnot(None),
        )
        .group_by(CompetitionScoreEvent.user_id)
        .all()
    )
    return {uid: int(total) for uid, total in rows}


def _team_scores(db: Session, comp: Competition) -> dict[int, int]:
    rows = (
        db.query(
            CompetitionScoreEvent.team_id,
            func.coalesce(func.sum(CompetitionScoreEvent.delta), 0),
        )
        .filter(
            CompetitionScoreEvent.competition_id == comp.id,
            CompetitionScoreEvent.team_id.isnot(None),
        )
        .group_by(CompetitionScoreEvent.team_id)
        .all()
    )
    return {tid: int(total) for tid, total in rows}


def _user_solves(db: Session, comp: Competition) -> dict[int, list[CompetitionSolve]]:
    rows = (
        db.query(CompetitionSolve)
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.user_id.isnot(None),
        )
        .order_by(CompetitionSolve.solved_at)
        .all()
    )
    grouped: dict[int, list[CompetitionSolve]] = {}
    for s in rows:
        grouped.setdefault(s.user_id, []).append(s)
    return grouped


def _team_solves(db: Session, comp: Competition) -> dict[int, list[CompetitionSolve]]:
    rows = (
        db.query(CompetitionSolve)
        .filter(
            CompetitionSolve.competition_id == comp.id,
            CompetitionSolve.team_id.isnot(None),
        )
        .order_by(CompetitionSolve.solved_at)
        .all()
    )
    grouped: dict[int, list[CompetitionSolve]] = {}
    for s in rows:
        grouped.setdefault(s.team_id, []).append(s)
    return grouped


def _challenge_slugs(db: Session, comp: Competition) -> dict[int, str]:
    from ..models_competitions import CompetitionChallenge
    rows = (
        db.query(CompetitionChallenge.id, CompetitionChallenge.slug)
        .filter(CompetitionChallenge.competition_id == comp.id)
        .all()
    )
    return {cid: slug for cid, slug in rows}


def _sort_rows(rows: Iterable[LeaderboardRow], tie_breaker: TieBreaker) -> list[LeaderboardRow]:
    rows = list(rows)
    if tie_breaker == TieBreaker.last_solve_time:
        # Больше очков; при равенстве — у кого last_solve_at РАНЬШЕ.
        rows.sort(key=lambda r: (
            -r.score,
            r.last_solve_at or datetime.max,
            r.name.lower(),
        ))
    elif tie_breaker == TieBreaker.first_solve_time:
        rows.sort(key=lambda r: (
            -r.score,
            r.first_solve_at or datetime.max,
            r.name.lower(),
        ))
    elif tie_breaker == TieBreaker.solves_count:
        rows.sort(key=lambda r: (-r.score, -r.solves_count, r.name.lower()))
    elif tie_breaker == TieBreaker.alphabetic:
        rows.sort(key=lambda r: (-r.score, r.name.lower()))
    else:
        rows.sort(key=lambda r: (-r.score, r.name.lower()))
    return rows


def _assign_ranks(rows: list[LeaderboardRow]) -> None:
    """Dense ranking: одинаковые очки → одинаковое место."""
    last_score: Optional[int] = None
    last_rank = 0
    for i, row in enumerate(rows, start=1):
        if last_score is None or row.score != last_score:
            last_rank = i
            last_score = row.score
        row.rank = last_rank


# ── Основной расчёт ──────────────────────────────────────────────────

def compute(db: Session, comp: Competition) -> LeaderboardSnapshot:
    user_scores = _user_scores(db, comp)
    team_scores = _team_scores(db, comp)
    user_solves = _user_solves(db, comp)
    team_solves = _team_solves(db, comp)
    slugs = _challenge_slugs(db, comp)

    individuals: list[LeaderboardRow] = []
    teams: list[LeaderboardRow] = []

    # Индивидуальные
    if comp.mode in (CompetitionMode.individual, CompetitionMode.both):
        user_ids = set(user_scores.keys()) | set(user_solves.keys())
        users = (
            db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        )
        user_by_id = {u.id: u for u in users}

        for uid in user_ids:
            u = user_by_id.get(uid)
            if not u:
                continue
            solves = user_solves.get(uid, [])
            row = LeaderboardRow(
                id=uid,
                name=u.username,
                score=user_scores.get(uid, 0),
                solves_count=len(solves),
                last_solve_at=solves[-1].solved_at if solves else None,
                first_solve_at=solves[0].solved_at if solves else None,
                is_team=False,
                solved_challenges={
                    slugs.get(s.challenge_id, str(s.challenge_id)): s.solved_at
                    for s in solves
                },
            )
            individuals.append(row)

        _assign_ranks(_sort_rows(individuals, comp.tie_breaker))

    # Командные
    if comp.mode in (CompetitionMode.team, CompetitionMode.both):
        team_ids = set(team_scores.keys()) | set(team_solves.keys())
        team_objs = (
            db.query(CompetitionTeam).filter(CompetitionTeam.id.in_(team_ids)).all()
            if team_ids else []
        )
        team_by_id = {t.id: t for t in team_objs}

        for tid in team_ids:
            t = team_by_id.get(tid)
            if not t:
                continue
            solves = team_solves.get(tid, [])
            members = (
                db.query(User.username)
                .join(CompetitionTeamMember, CompetitionTeamMember.user_id == User.id)
                .filter(
                    CompetitionTeamMember.team_id == tid,
                    CompetitionTeamMember.status == TeamMemberStatus.accepted,
                )
                .all()
            )
            row = LeaderboardRow(
                id=tid,
                name=t.name,
                score=team_scores.get(tid, 0),
                solves_count=len(solves),
                last_solve_at=solves[-1].solved_at if solves else None,
                first_solve_at=solves[0].solved_at if solves else None,
                is_team=True,
                members=[m[0] for m in members],
                solved_challenges={
                    slugs.get(s.challenge_id, str(s.challenge_id)): s.solved_at
                    for s in solves
                },
            )
            teams.append(row)

        _assign_ranks(_sort_rows(teams, comp.tie_breaker))

    return LeaderboardSnapshot(
        competition_id=comp.id,
        competition_slug=comp.slug,
        mode=comp.mode.value if hasattr(comp.mode, "value") else str(comp.mode),
        generated_at=datetime.utcnow(),
        individuals=individuals,
        teams=teams,
    )


# ── Экспорт ──────────────────────────────────────────────────────────

def to_csv(snapshot: LeaderboardSnapshot) -> str:
    lines = ["type,rank,name,score,solves,last_solve_at"]
    for row in snapshot.individuals:
        lines.append(",".join([
            "individual",
            str(row.rank),
            _csv_escape(row.name),
            str(row.score),
            str(row.solves_count),
            row.last_solve_at.isoformat() if row.last_solve_at else "",
        ]))
    for row in snapshot.teams:
        lines.append(",".join([
            "team",
            str(row.rank),
            _csv_escape(row.name),
            str(row.score),
            str(row.solves_count),
            row.last_solve_at.isoformat() if row.last_solve_at else "",
        ]))
    return "\n".join(lines)


def _csv_escape(value: str) -> str:
    if any(c in value for c in [",", '"', "\n"]):
        return '"' + value.replace('"', '""') + '"'
    return value