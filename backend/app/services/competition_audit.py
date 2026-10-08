"""Аудит действий в соревновании."""
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import User
from ..models_competitions import CompetitionAuditLog


def log_action(
    db: Session,
    *,
    competition_id: int,
    actor: Optional[User],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> CompetitionAuditLog:
    entry = CompetitionAuditLog(
        competition_id=competition_id,
        actor_id=actor.id if actor else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        payload_json=payload or {},
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry