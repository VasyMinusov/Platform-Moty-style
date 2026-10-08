"""Сервис уведомлений.

- Создаёт запись в БД.
- Публикует событие в WebSocket-хаб пользователя, чтобы фронт получил
  push в реальном времени.
"""
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User
from ..models_competitions import CompetitionModerator, Competition
from ..models_notifications import Notification, NotificationLevel
from .competition_stream import publish_sync


def _broadcast(user_id: int, notification: Notification) -> None:
    """Публикует событие в канал пользователя. Не валит операцию при ошибке."""
    try:
        publish_sync(f"user:{user_id}", {
            "type": "notification.created",
            "data": {
                "id": notification.id,
                "notification_type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "level": notification.level.value if hasattr(notification.level, "value") else str(notification.level),
                "link": notification.link,
                "payload": notification.payload_json or {},
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            },
        })
    except Exception:
        pass


def push(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    message: str = "",
    level: str = "info",
    link: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> Notification:
    try:
        level_enum = NotificationLevel(level)
    except ValueError:
        level_enum = NotificationLevel.info

    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message or "",
        level=level_enum,
        link=link,
        payload_json=payload or {},
        read=False,
    )
    db.add(n)
    if commit:
        db.commit()
        db.refresh(n)
    else:
        db.flush()

    _broadcast(user_id, n)
    return n


def push_many(
    db: Session,
    *,
    user_ids: Iterable[int],
    type: str,
    title: str,
    message: str = "",
    level: str = "info",
    link: Optional[str] = None,
    payload: Optional[dict] = None,
    commit: bool = True,
) -> list[Notification]:
    result = []
    seen = set()
    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)
        result.append(push(
            db,
            user_id=uid,
            type=type, title=title, message=message, level=level,
            link=link, payload=payload, commit=False,
        ))
    if commit:
        db.commit()
        for n in result:
            db.refresh(n)
    return result


def push_to_competition_staff(
    db: Session,
    *,
    competition: Competition,
    type: str,
    title: str,
    message: str = "",
    level: str = "info",
    link: Optional[str] = None,
    payload: Optional[dict] = None,
    include_admin: bool = True,
) -> list[Notification]:
    """Шлёт уведомление ответственным модераторам соревнования и (опционально)
    всем админам."""
    user_ids: set[int] = set()

    mods = (
        db.query(CompetitionModerator.user_id)
        .filter(CompetitionModerator.competition_id == competition.id)
        .all()
    )
    for (uid,) in mods:
        user_ids.add(uid)

    if include_admin:
        admins = db.query(User.id).filter(User.role == "admin").all()
        for (uid,) in admins:
            user_ids.add(uid)

    return push_many(
        db,
        user_ids=user_ids,
        type=type, title=title, message=message, level=level,
        link=link, payload=payload,
    )


def list_for_user(
    db: Session,
    user_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
) -> tuple[list[Notification], int]:
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.read.is_(False))

    total_unread = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.read.is_(False))
        .scalar() or 0
    )

    items = (
        q.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return items, int(total_unread)


def mark_read(db: Session, user_id: int, notification_id: int) -> Optional[Notification]:
    n = (
        db.query(Notification)
        .filter_by(id=notification_id, user_id=user_id)
        .first()
    )
    if not n:
        return None
    if not n.read:
        n.read = True
        db.commit()
        db.refresh(n)
    return n


def mark_all_read(db: Session, user_id: int) -> int:
    q = db.query(Notification).filter_by(user_id=user_id, read=False)
    count = q.count()
    if count:
        q.update({Notification.read: True}, synchronize_session=False)
        db.commit()
    return count


def delete(db: Session, user_id: int, notification_id: int) -> bool:
    n = (
        db.query(Notification)
        .filter_by(id=notification_id, user_id=user_id)
        .first()
    )
    if not n:
        return False
    db.delete(n)
    db.commit()
    return True


def clear_all(db: Session, user_id: int) -> int:
    q = db.query(Notification).filter_by(user_id=user_id)
    count = q.count()
    if count:
        q.delete(synchronize_session=False)
        db.commit()
    return count