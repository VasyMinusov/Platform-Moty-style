import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Lesson, User
from ..schemas import LessonCreate, LessonOut, LessonUpdate
from ..security import get_current_user, require_moderator

router = APIRouter(prefix="/lessons", tags=["lessons"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _serialize(lesson: Lesson) -> dict:
    return {
        "id": lesson.id,
        "slug": lesson.slug,
        "title": lesson.title,
        "summary": lesson.summary or "",
        "content_md": lesson.content_md or "",
        "author_id": lesson.author_id,
        "author_username": lesson.author.username if lesson.author else None,
        "created_at": lesson.created_at,
        "updated_at": lesson.updated_at,
    }


def _validate_slug(slug: str):
    if not _SLUG_RE.match(slug or ""):
        raise HTTPException(
            400,
            "Slug must be kebab-case: lowercase latin letters, digits and hyphens",
        )


@router.get("", response_model=list[LessonOut])
def list_lessons(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Список занятий библиотеки. Доступен любому авторизованному пользователю."""
    lessons = db.query(Lesson).order_by(Lesson.created_at.desc()).all()
    return [_serialize(l) for l in lessons]


@router.get("/{slug}", response_model=LessonOut)
def get_lesson(
    slug: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    lesson = db.query(Lesson).filter(Lesson.slug == slug).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return _serialize(lesson)


@router.post("", response_model=LessonOut)
def create_lesson(
    payload: LessonCreate,
    db: Session = Depends(get_db),
    author: User = Depends(require_moderator),
):
    """Создать занятие (модератор или админ)."""
    _validate_slug(payload.slug)
    if db.query(Lesson).filter(Lesson.slug == payload.slug).first():
        raise HTTPException(409, "Lesson with this slug already exists")
    lesson = Lesson(
        slug=payload.slug,
        title=payload.title,
        summary=payload.summary or "",
        content_md=payload.content_md or "",
        author_id=author.id,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return _serialize(lesson)


@router.put("/{slug}", response_model=LessonOut)
def update_lesson(
    slug: str,
    payload: LessonUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_moderator),
):
    """Редактировать занятие (модератор или админ)."""
    lesson = db.query(Lesson).filter(Lesson.slug == slug).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")

    if payload.slug is not None and payload.slug != lesson.slug:
        _validate_slug(payload.slug)
        clash = db.query(Lesson).filter(Lesson.slug == payload.slug).first()
        if clash:
            raise HTTPException(409, "Lesson with this slug already exists")
        lesson.slug = payload.slug
    if payload.title is not None:
        lesson.title = payload.title
    if payload.summary is not None:
        lesson.summary = payload.summary
    if payload.content_md is not None:
        lesson.content_md = payload.content_md

    db.commit()
    db.refresh(lesson)
    return _serialize(lesson)


@router.delete("/{slug}")
def delete_lesson(
    slug: str,
    db: Session = Depends(get_db),
    _=Depends(require_moderator),
):
    """Удалить занятие (модератор или админ)."""
    lesson = db.query(Lesson).filter(Lesson.slug == slug).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    db.delete(lesson)
    db.commit()
    return {"deleted": True}
