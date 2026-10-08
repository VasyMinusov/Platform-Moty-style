from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_MAX_PASSWORD_BYTES = 72


def _normalize(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_normalize(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    if getattr(user, "is_blocked", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is blocked")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_moderator(user: User = Depends(get_current_user)) -> User:
    """Модераторы и администраторы (просмотр пользователей, ведение библиотеки)."""
    if user.role not in (UserRole.admin, UserRole.moderator):
        raise HTTPException(status_code=403, detail="Moderator or admin only")
    return user


# Псевдоним для модуля соревнований — читается лучше.
require_staff = require_moderator


# ══════════════════════════════════════════════════════════════════════
# Доступ к конкретному соревнованию
# ══════════════════════════════════════════════════════════════════════

def competition_moderator_required(
    *,
    require_responsible: bool = False,
    allow_creator_prepublish: bool = True,
):
    """Фабрика зависимостей: возвращает функцию, которая проверяет, что
    текущий пользователь — админ, или назначенный на это соревнование
    модератор (роль responsible/helper).

    Дополнительно: до публикации (status=draft) создатель-модератор имеет
    доступ к своему соревнованию, даже если он ещё не в списке
    competition_moderators.
    """
    # Импорт внутри функции — чтобы избежать циклического импорта на
    # уровне модуля: security.py импортируется из многих мест.
    from .models_competitions import (
        Competition,
        CompetitionModerator,
        ModeratorRole,
        CompetitionStatus,
    )

    def _dep(
        slug: str,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        competition = (
            db.query(Competition)
            .filter(Competition.slug == slug, Competition.deleted_at.is_(None))
            .first()
        )
        if not competition:
            raise HTTPException(404, "Competition not found")

        # Админ — всегда.
        if user.role == UserRole.admin:
            return user

        # Модератор — только если назначен, либо (для draft) — создатель.
        if user.role == UserRole.moderator:
            if allow_creator_prepublish \
                    and competition.status == CompetitionStatus.draft \
                    and competition.created_by == user.id:
                return user

            m = (
                db.query(CompetitionModerator)
                .filter_by(competition_id=competition.id, user_id=user.id)
                .first()
            )
            if not m:
                raise HTTPException(403, "You are not a moderator of this competition")
            if require_responsible and m.role != ModeratorRole.responsible:
                raise HTTPException(403, "Responsible moderator role required")
            return user

        raise HTTPException(403, "Admin or moderator only")

    return _dep