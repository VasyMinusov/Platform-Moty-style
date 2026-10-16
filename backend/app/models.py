import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint, Text,
    Index, text,
)
from sqlalchemy.orm import relationship

from .database import Base

from . import models_notifications  # noqa: E402,F401


class UserRole(str, enum.Enum):
    student = "student"
    moderator = "moderator"
    admin = "admin"


class User(Base):
    """
    Локальный профиль CTF-платформы.

    Источник истины для credentials (пароль, MFA, email verification) —
    auth-service. Здесь только CTF-специфичные поля: role, points,
    status, is_blocked.

    id совпадает с id пользователя в auth-service (claims.sub в JWT).
    autoincrement=False: значения приходят извне, БД не генерирует.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)

    # CTF-специфичная роль. Отличается от auth-service.is_admin —
    # там «может управлять аккаунтами», здесь «админ CTF-мероприятия».
    role = Column(Enum(UserRole), default=UserRole.student, nullable=False)
    points = Column(Integer, default=0, nullable=False)

    # Произвольный статус, отображаемый как #статус.
    status = Column(String(64), nullable=True)

    # Локальная блокировка (независима от auth-service).
    is_blocked = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # ── password_hash удалён — credentials живут в auth-service ──

    solves = relationship("Solve", back_populates="user")
    instances = relationship("ChallengeInstance", back_populates="user")
    lessons = relationship("Lesson", back_populates="author")


class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    difficulty = Column(String(32), nullable=False, default="easy")
    points = Column(Integer, nullable=False, default=100)
    description = Column(String(4000), default="")
    flag_hash = Column(String(255), nullable=False)
    container_port = Column(Integer, nullable=False, default=80)
    enabled = Column(Boolean, default=True)

    solves = relationship("Solve", back_populates="challenge")
    instances = relationship("ChallengeInstance", back_populates="challenge")


class ChallengeInstance(Base):
    __tablename__ = "challenge_instances"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    container_id = Column(String(128), nullable=False)
    host_port = Column(Integer, nullable=False)
    status = Column(String(32), default="running")
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    # ── Поля модуля «Соревнования» ───────────────────────────────
    competition_id = Column(
        Integer,
        ForeignKey("competitions.id", ondelete="SET NULL"),
        nullable=True,
    )
    team_id = Column(
        Integer,
        ForeignKey("competition_teams.id", ondelete="SET NULL"),
        nullable=True,
    )
    challenge_kind = Column(String(16), default="docker", nullable=False)
    dynamic_flag_hash = Column(String(255), nullable=True)

    user = relationship("User", back_populates="instances")
    challenge = relationship("Challenge", back_populates="instances")

    __table_args__ = (
        Index(
            "uq_ci_global",
            "user_id",
            "challenge_id",
            unique=True,
            postgresql_where=text("competition_id IS NULL"),
        ),
        Index(
            "uq_ci_comp_user",
            "competition_id",
            "challenge_id",
            "user_id",
            unique=True,
            postgresql_where=text("competition_id IS NOT NULL AND team_id IS NULL"),
        ),
        Index(
            "uq_ci_comp_team",
            "competition_id",
            "challenge_id",
            "team_id",
            unique=True,
            postgresql_where=text("competition_id IS NOT NULL AND team_id IS NOT NULL"),
        ),
    )


class Solve(Base):
    __tablename__ = "solves"
    __table_args__ = (UniqueConstraint("user_id", "challenge_id", name="uq_solve_once"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    solved_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="solves")
    challenge = relationship("Challenge", back_populates="solves")


class Writeup(Base):
    """Write-up (решение) для задания. Хранится как JSON-структура."""
    __tablename__ = "writeups"

    id = Column(Integer, primary_key=True)
    challenge_slug = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Lesson(Base):
    """Занятие (статья) библиотеки. Текст хранится в Markdown."""
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(String(500), default="")
    content_md = Column(Text, nullable=False, default="")
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = relationship("User", back_populates="lessons")


# ── Модуль «Соревнования» ──
from . import models_competitions  # noqa: E402,F401