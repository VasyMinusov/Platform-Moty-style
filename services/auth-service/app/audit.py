"""
Единая точка записи в audit_logs.

Вынесено из роутеров, чтобы избежать дублирования: `auth.py`,
`users.py`, `mfa.py` пишут однотипные события. correlation_id
берётся автоматически из contextvars.

metadata_json — JSONB. Принимаем dict, а не строку:
- Postgres валидирует JSON на входе.
- Запросы вида `WHERE metadata_json @> '{"reason":"replay"}'`
  используют GIN-индекс (ix_audit_logs_metadata).
- Не нужно парсить строку на стороне БД для аналитики.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_correlation_id
from app.models import AuditAction, AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: AuditAction,
    success: bool,
    client: dict[str, str | None],
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Записать действие в аудит-лог.

    Аргументы:
        metadata: произвольный JSON-сериализуемый dict. Примеры:
            {"reason": "invalid_password"}
            {"stage": "mfa", "used_backup": True}
            {"target_user_id": 42, "count": 3}

    НЕ коммитит — это ответственность вызывающего кода. Если
    вызывающий бросает исключение ПОСЛЕ write_audit, но хочет
    сохранить запись — обязан сделать `await db.commit()` до raise
    (иначе get_db() откатит на rollback()).
    """
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            success=success,
            ip_address=client.get("ip_address"),
            user_agent=client.get("user_agent"),
            correlation_id=get_correlation_id(),
            metadata_json=metadata,
        )
    )
