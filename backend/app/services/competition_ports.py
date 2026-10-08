"""Выделение диапазона портов под соревнование.

Использует существующий общий диапазон из settings.challenge_port_range_*
и нарезает его на поддиапазоны по 100 портов.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models_competitions import Competition


BLOCK_SIZE = 100


def _taken_blocks(db: Session) -> list[tuple[int, int]]:
    rows = (
        db.query(Competition.port_range_start, Competition.port_range_end)
        .filter(
            Competition.port_range_start.isnot(None),
            Competition.port_range_end.isnot(None),
            Competition.deleted_at.is_(None),
        )
        .all()
    )
    return [(s, e) for (s, e) in rows if s and e]


def allocate_port_range(db: Session, competition: Competition) -> tuple[int, int]:
    """Возвращает свободный блок портов. Если у соревнования уже есть —
    возвращает текущий. Иначе ищет первый свободный в общем диапазоне."""
    if competition.port_range_start and competition.port_range_end:
        return competition.port_range_start, competition.port_range_end

    start = settings.challenge_port_range_start
    end = settings.challenge_port_range_end
    taken = _taken_blocks(db)

    block_start = start
    while block_start + BLOCK_SIZE - 1 <= end:
        block_end = block_start + BLOCK_SIZE - 1
        # Пересечение с любым занятым блоком?
        if any(not (block_end < s or block_start > e) for (s, e) in taken):
            block_start += BLOCK_SIZE
            continue
        competition.port_range_start = block_start
        competition.port_range_end = block_end
        return block_start, block_end

    raise RuntimeError("No free port range available for competition")