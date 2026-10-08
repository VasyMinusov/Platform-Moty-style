"""WebSocket-канал соревнования: live-лидерборд и события.

Ключ канала в хабе — `comp:{slug}`. Тот же ключ используется в
notification_service для личных каналов `user:{id}`, поэтому hub
обслуживает оба типа каналов единообразно.
"""
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from ..config import settings
from ..database import SessionLocal
from ..models import User
from ..models_competitions import (
    ApplicationStatus,
    CompetitionApplication,
    CompetitionTeam,
    CompetitionTeamMember,
    LeaderboardVisibility,
    TeamMemberStatus,
)
from ..services import competition_leaderboard_service as lb
from ..services import competition_service
from ..services.competition_stream import hub


router = APIRouter(tags=["competitions:ws"])


def _decode_username(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
        )
        return payload.get("sub")
    except JWTError:
        return None


def _can_view_leaderboard(db, comp, user: Optional[User]) -> bool:
    vis = comp.leaderboard_visibility
    vis_val = vis.value if hasattr(vis, "value") else str(vis)
    if vis_val == LeaderboardVisibility.public.value:
        return True
    if user is None:
        return False
    if user.role.value in ("admin", "moderator"):
        return True
    if vis_val == LeaderboardVisibility.hidden.value:
        return False

    # participants — только для одобренных
    app = (
        db.query(CompetitionApplication)
        .filter_by(competition_id=comp.id, user_id=user.id)
        .first()
    )
    if app and app.status == ApplicationStatus.approved:
        return True

    team_ids = [
        t.id for (t,) in (
            db.query(CompetitionTeam.id)
            .join(
                CompetitionTeamMember,
                CompetitionTeamMember.team_id == CompetitionTeam.id,
            )
            .filter(
                CompetitionTeam.competition_id == comp.id,
                CompetitionTeamMember.user_id == user.id,
                CompetitionTeamMember.status == TeamMemberStatus.accepted,
            )
            .all()
        )
    ]
    if team_ids:
        team_app = (
            db.query(CompetitionApplication)
            .filter(
                CompetitionApplication.competition_id == comp.id,
                CompetitionApplication.team_id.in_(team_ids),
                CompetitionApplication.status == ApplicationStatus.approved,
            )
            .first()
        )
        if team_app:
            return True

    return False


@router.websocket("/competitions/{slug}/stream")
async def stream(websocket: WebSocket, slug: str, token: str = Query(None)):
    await websocket.accept()

    db = SessionLocal()
    channel = f"comp:{slug}"
    try:
        try:
            comp = competition_service.get_by_slug(db, slug)
        except Exception:
            await websocket.close(code=1008)
            return

        username = _decode_username(token)
        user = (
            db.query(User).filter(User.username == username).first()
            if username else None
        )

        if not _can_view_leaderboard(db, comp, user):
            await websocket.close(code=1008)
            return

        await hub.subscribe(channel, websocket)

        # Первый снапшот сразу, чтобы фронт не ждал.
        snapshot = lb.compute(db, comp)
        await websocket.send_json({
            "type": "leaderboard.snapshot",
            "data": {
                "individuals": [
                    {
                        "rank": r.rank, "id": r.id, "name": r.name,
                        "score": r.score, "solves": r.solves_count,
                    }
                    for r in snapshot.individuals
                ],
                "teams": [
                    {
                        "rank": r.rank, "id": r.id, "name": r.name,
                        "score": r.score, "solves": r.solves_count,
                    }
                    for r in snapshot.teams
                ],
            },
        })

        # Держим соединение открытым, читаем пинги/сообщения клиента.
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        try:
            await hub.unsubscribe(channel, websocket)
        except Exception:
            pass
        db.close()