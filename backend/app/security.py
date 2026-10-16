"""
Аутентификация и авторизация.

После интеграции с auth-service:
- JWT генерирует auth-service (HS256, тот же секрет).
- Мы только валидируем токен (подпись, iss, aud, exp, typ=access).
- Если локального User с id=sub нет — provision: запрашиваем профиль
  у auth-service /api/v1/users/me и создаём локальную запись.

Функции хеширования паролей (bcrypt) удалены — они больше не нужны.
"""
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, UserRole


# auto_error=False: даём возможность вернуть наш формат ошибки, а не
# дефолтный 403 от FastAPI.
_bearer = HTTPBearer(auto_error=False)


# ════════════════════════════════════════════════════════════════════
# JWT validation
# ════════════════════════════════════════════════════════════════════


def _decode_access_token(token: str) -> dict:
    """
    Декодировать и валидировать access-токен от auth-service.

    Проверяем:
    - подпись (HS256, общий секрет)
    - iss/aud (должны совпадать с auth-service)
    - exp (leeway 30 сек для дрейфа часов)
    - typ == "access" (refresh/mfa_pending не принимаем как access)
    """
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"leeway": 30},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("typ") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not an access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ════════════════════════════════════════════════════════════════════
# Lazy provisioning
# ════════════════════════════════════════════════════════════════════


def _provision_local_user(db: Session, *, user_id: int, token: str) -> Optional[User]:
    """
    Создать локальную запись User для аутентифицированного пользователя
    auth-service.

    Вызывается ОДИН раз за жизнь пользователя — при первом успешном
    запросе к ctf-backend. Запрашивает профиль у auth-service и
    копирует id/username/email. Роль по умолчанию — student.

    Race condition: если два параллельных запроса увидят отсутствие
    User, оба попробуют создать. Один упадёт с IntegrityError на
    unique-констрейнте — вернём None (запрос получит 401, следующий
    пройдёт уже с созданной записью).
    """
    try:
        r = httpx.get(
            f"{settings.auth_service_url}/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None

    if r.status_code != 200:
        return None

    data = r.json()

    user = User(
        id=user_id,
        username=data["username"],
        email=data["email"],
        role=UserRole.student,
        points=0,
        status=None,
        is_blocked=False,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        return None

    return user


# ════════════════════════════════════════════════════════════════════
# FastAPI dependencies
# ════════════════════════════════════════════════════════════════════


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    Извлечь и валидировать JWT, вернуть локального User.

    Если пользователя ещё нет в локальной БД (первый запрос после
    регистрации в auth-service) — provision: запрашиваем профиль
    у auth-service и создаём запись.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = _decode_access_token(token)

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        user = _provision_local_user(db, user_id=user_id, token=token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found in local DB and provisioning failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if user.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is blocked",
        )

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_moderator(user: User = Depends(get_current_user)) -> User:
    """Модераторы и администраторы (просмотр пользователей, библиотека)."""
    if user.role not in (UserRole.admin, UserRole.moderator):
        raise HTTPException(status_code=403, detail="Moderator or admin only")
    return user


# Псевдоним для модуля соревнований.
require_staff = require_moderator


# ════════════════════════════════════════════════════════════════════
# Доступ к конкретному соревнованию
# ════════════════════════════════════════════════════════════════════


def competition_moderator_required(
    *,
    require_responsible: bool = False,
    allow_creator_prepublish: bool = True,
):
    """
    Фабрика зависимостей: проверяет, что текущий пользователь — админ,
    или назначенный на это соревнование модератор.

    До публикации (status=draft) создатель-модератор имеет доступ
    к своему соревнованию, даже если ещё не в списке moderators.
    """
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