from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Users ─────────────────────────────────────────────────────────────
#
# UserCreate и Token удалены — регистрация/логин теперь на auth-service.
# Остались только схемы для локального профиля CTF-платформы.


class UserOut(BaseModel):
    id: int
    username: str
    # str, а не EmailStr: в БД могут быть адреса, которые pydantic
    # считает невалидными (например admin@ctf-platform.localhost).
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


# ── Challenges ────────────────────────────────────────────────────────


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


# ── Write-ups ────────────────────────────────────────────────────────


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


# ── Lessons ──────────────────────────────────────────────────────────


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

# ── Instances (детальный вид для UI) ────────────────────────────────────
#
# Используется:
#   - GET /challenges/instances/running      (свои глобальные инстансы)
#   - GET /admin/instances                   (все инстансы, админ)


class InstanceDetailOut(BaseModel):
    """
    Инстанс задания с URL, построенным для клиента, который сделал
    запрос.

    `url` строится из Host / X-Forwarded-Host запроса — если студент
    зашёл с 192.168.1.5, инстанс откроется на http://192.168.1.5:30001,
    а не на 127.0.0.1:30001.

    scope:
        "global"      — инстанс глобального Challenge (из /challenges)
        "competition" — инстанс CompetitionChallenge (из соревнования)
    """
    id: int
    scope: str = "global"
    user_id: int
    username: Optional[str] = None
    challenge_id: int
    challenge_slug: str
    challenge_title: str
    container_id: str
    host_port: int
    url: str
    status: str
    started_at: Optional[datetime] = None
    expires_at: datetime
    is_expired: bool = False
    # None — не проверяли (дешевле для публичного списка).
    # True/False — результат docker inspect (для админского списка).
    is_alive: Optional[bool] = None
    # Для scope="competition": slug соревнования.
    competition_slug: Optional[str] = None


class AdminInstancesListOut(BaseModel):
    items: list[InstanceDetailOut]
    total: int

