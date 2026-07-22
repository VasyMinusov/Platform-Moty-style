from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# bcrypt физически не может захэшировать больше 72 байт пароля — в новых
# версиях библиотеки (4.1+) это не молча обрезается, а падает с ValueError.
# Раньше это маскировалось passlib, но и там был сломан бэкенд-детект (см.
# ниже). Обрезаем длину явно и предсказуемо — 72 байта уже с большим запасом
# достаточно для стойкого пароля, это не ослабляет защиту.
_MAX_PASSWORD_BYTES = 72


def _normalize(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_normalize(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize(plain), hashed.encode("utf-8"))
    except ValueError:
        # Например, hashed пришёл в неожиданном формате — считаем, что пароль неверный,
        # а не роняем запрос 500-й ошибкой.
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is blocked",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_moderator(user: User = Depends(get_current_user)) -> User:
    """Доступ для модераторов и администраторов
    (просмотр пользователей, ведение библиотеки занятий)."""
    if user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Moderator or admin only")
    return user

