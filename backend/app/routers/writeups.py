from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Writeup, Challenge, Solve, User, UserRole
from ..schemas import WriteupOut, WriteupCreate, WriteupUpdate
from ..security import require_admin, get_current_user

router = APIRouter(prefix="/writeups", tags=["writeups"])


@router.get("", response_model=list[WriteupOut])
def list_writeups(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Список write-ups, доступных текущему пользователю.
    - Админ видит все write-up'ы.
    - Обычный пользователь видит только те, для которых у него есть решение."""
    if user.role == UserRole.admin:
        return db.query(Writeup).all()

    # Получаем slug'и заданий, решённых пользователем
    solved_slugs = (
        db.query(Challenge.slug)
        .join(Solve, Solve.challenge_id == Challenge.id)
        .filter(Solve.user_id == user.id)
        .all()
    )
    solved_slugs = [slug for (slug,) in solved_slugs]

    return db.query(Writeup).filter(Writeup.challenge_slug.in_(solved_slugs)).all()


@router.get("/{slug}", response_model=WriteupOut)
def get_writeup(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Получить write-up по slug задания.
    Доступен только если пользователь решил задание или является админом."""
    w = db.query(Writeup).filter(Writeup.challenge_slug == slug).first()
    if not w:
        raise HTTPException(404, "Write-up not found")

    # Проверка доступа
    if user.role != UserRole.admin:
        solved = (
            db.query(Solve)
            .join(Challenge, Solve.challenge_id == Challenge.id)
            .filter(Solve.user_id == user.id, Challenge.slug == slug)
            .first()
        )
        if not solved:
            raise HTTPException(
                status_code=403,
                detail="You have not solved this challenge yet",
            )

    return w


@router.post("", response_model=WriteupOut)
def create_writeup(
    payload: WriteupCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Создать write-up (только админ)."""
    existing = (
        db.query(Writeup)
        .filter(Writeup.challenge_slug == payload.challenge_slug)
        .first()
    )
    if existing:
        raise HTTPException(409, "Write-up for this challenge already exists")
    w = Writeup(
        challenge_slug=payload.challenge_slug,
        title=payload.title,
        content_json=payload.content_json,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.put("/{slug}", response_model=WriteupOut)
def update_writeup(
    slug: str,
    payload: WriteupUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Обновить write-up (только админ)."""
    w = db.query(Writeup).filter(Writeup.challenge_slug == slug).first()
    if not w:
        raise HTTPException(404, "Write-up not found")
    if payload.title is not None:
        w.title = payload.title
    if payload.content_json is not None:
        w.content_json = payload.content_json
    db.commit()
    db.refresh(w)
    return w


@router.delete("/{slug}")
def delete_writeup(
    slug: str,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Удалить write-up (только админ)."""
    w = db.query(Writeup).filter(Writeup.challenge_slug == slug).first()
    if not w:
        raise HTTPException(404, "Write-up not found")
    db.delete(w)
    db.commit()
    return {"deleted": True}