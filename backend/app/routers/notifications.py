"""Роутер уведомлений: REST + WebSocket."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import User
from ..schemas_notifications import (
    NotificationListOut, NotificationOut, UnreadCountOut,
)
from ..security import get_current_user
from ..services import notification_service
from ..services.competition_stream import hub


router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── REST ─────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationListOut)
def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, unread = notification_service.list_for_user(
        db, user.id,
        limit=limit, offset=offset, unread_only=unread_only,
    )
    return NotificationListOut(
        items=[NotificationOut.model_validate(n) for n in items],
        unread_count=unread,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, unread = notification_service.list_for_user(db, user.id, limit=0)
    return UnreadCountOut(unread_count=unread)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = notification_service.mark_read(db, user.id, notification_id)
    if not n:
        from fastapi import HTTPException
        raise HTTPException(404, "Notification not found")
    return n


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = notification_service.mark_all_read(db, user.id)
    return {"updated": count}


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ok = notification_service.delete(db, user.id, notification_id)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(404, "Notification not found")
    return {"deleted": True}


@router.delete("")
def clear_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = notification_service.clear_all(db, user.id)
    return {"deleted": count}


# ── WebSocket ────────────────────────────────────────────────────────

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


@router.websocket("/stream")
async def stream(websocket: WebSocket, token: str = Query(None)):
    await websocket.accept()

    username = _decode_username(token)
    if not username:
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            await websocket.close(code=1008)
            return

        channel = f"user:{user.id}"
        await hub.subscribe(channel, websocket)

        # Начальный unread count, чтобы фронт сразу знал.
        _, unread = notification_service.list_for_user(db, user.id, limit=0)
        await websocket.send_json({
            "type": "notifications.hello",
            "data": {"unread_count": unread},
        })

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
    finally:
        try:
            if user := locals().get("user"):
                await hub.unsubscribe(f"user:{user.id}", websocket)
        except Exception:
            pass
        db.close()