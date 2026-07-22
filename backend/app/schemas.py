from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    # str, а не EmailStr: в БД могут быть адреса, которые pydantic считает
    # невалидными (например admin@ctf-platform.localhost у дефолтного админа)
    email: str
    role: str
    points: int
    status: Optional[str] = None
    is_blocked: bool = False

    class Config:
        from_attributes = True

class AdminUserUpdate(BaseModel):
    """Правки пользователя администратором: статус и блокировка."""
    status: Optional[str] = None
    is_blocked: Optional[bool] = None


class RoleUpdate(BaseModel):
    """Смена роли пользователя (только админ)."""
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChallengeOut(BaseModel):
    id: int
    slug: str
    title: str
    category: str
    difficulty: str
    points: int
    description: str
    solved: bool = False

    class Config:
        from_attributes = True


class InstanceOut(BaseModel):
    challenge_slug: str
    url: str
    expires_at: datetime


class FlagSubmit(BaseModel):
    flag: str


class SubmitResult(BaseModel):
    correct: bool
    message: str
    points_awarded: Optional[int] = None


# ── Write-up schemas ──

class WriteupCreate(BaseModel):
    challenge_slug: str
    title: str
    content_json: str  # JSON-строка с шагами решения


class WriteupUpdate(BaseModel):
    title: Optional[str] = None
    content_json: Optional[str] = None


class WriteupOut(BaseModel):
    id: int
    challenge_slug: str
    title: str
    content_json: str
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Lesson (библиотека занятий) schemas ──

class LessonCreate(BaseModel):
    title: str
    slug: str
    summary: Optional[str] = ""
    content_md: str = ""


class LessonUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    summary: Optional[str] = None
    content_md: Optional[str] = None


class LessonOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    content_md: str
    author_id: int
    author_username: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

