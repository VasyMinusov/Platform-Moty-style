import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from .config import settings
from .middleware.rate_limit import RateLimitMiddleware
from .routers import (
    auth, challenges, admin, writeups, lessons,
    competitions, competitions_teams, competitions_challenges,
    competitions_instances, competitions_leaderboard,
    competitions_dashboard, competitions_appeals, competitions_ws,
    notifications,
)
from .services import challenge_registry
from .models import User, UserRole
from .security import hash_password

# Импорт новых моделей — гарантирует, что Base.metadata содержит и таблицы
# соревнований (нужно Alembic'у при autogenerate и create_all на чистой БД).
from . import models_competitions  # noqa: F401

app = FastAPI(title="CTF Training Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.rate_limit_enabled:
    app.add_middleware(RateLimitMiddleware)

app.include_router(auth.router)
app.include_router(challenges.router)
app.include_router(admin.router)
app.include_router(writeups.router)
app.include_router(lessons.router)
app.include_router(competitions.router)
app.include_router(competitions.admin_router)
app.include_router(competitions_teams.router)
app.include_router(competitions_challenges.router)
app.include_router(competitions_challenges.admin_router)
app.include_router(competitions_instances.router)
app.include_router(competitions_leaderboard.router)
app.include_router(competitions_dashboard.router)
app.include_router(competitions_appeals.router)
app.include_router(competitions_appeals.admin_router)
app.include_router(competitions_ws.router)
app.include_router(notifications.router)

# ── Alembic ──────────────────────────────────────────────────────────

def _alembic_config():
    """Возвращает Config для Alembic или None, если alembic.ini не найден
    (например, при запуске вообще без Alembic в окружении)."""
    from alembic.config import Config

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(backend_root, "alembic.ini")
    if not os.path.exists(cfg_path):
        return None

    cfg = Config(cfg_path)
    cfg.set_main_option("script_location", os.path.join(backend_root, "alembic"))
    return cfg


def _bootstrap_legacy_db():
    """Если в БД уже есть таблица users, но нет alembic_version — значит
    БД была создана старым create_all и НЕ является управляемой Alembic.
    Стампим её первой ревизией (0001_legacy), чтобы при upgrade не
    пересоздавались старые таблицы."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    if "alembic_version" in tables:
        return
    if "users" not in tables:
        return

    from alembic import command

    cfg = _alembic_config()
    if cfg is None:
        print("[INIT] alembic.ini не найден — пропускаю bootstrap legacy-БД")
        return

    command.stamp(cfg, "0001_legacy")
    print("[INIT] Обнаружена legacy-БД: застамплена как 0001_legacy")


def _run_alembic_migrations():
    """alembic upgrade head. Создаёт таблицы соревнований и все последующие
    изменения схемы."""
    from alembic import command

    cfg = _alembic_config()
    if cfg is None:
        print("[INIT] alembic.ini не найден — пропускаю Alembic-миграции")
        return

    command.upgrade(cfg, "head")


def _run_legacy_ddl():
    """Исторические идемпотентные ALTER'ы для очень старых БД, которые
    не проходили через Alembic. Новые изменения схемы сюда добавлять
    НЕЛЬЗЯ — только через Alembic-миграции."""
    from sqlalchemy import text

    ddl = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


# ── Прочее ───────────────────────────────────────────────────────────

def _ensure_admin_exists(db: Session):
    """Создаёт дефолтного админа и модератора, если в БД ещё нет ни одного админа.
    Учётные данные берутся из переменных окружения (ADMIN_USERNAME/ADMIN_PASSWORD,
    MODERATOR_USERNAME/MODERATOR_PASSWORD)."""
    admin_exists = db.query(User).filter(User.role == UserRole.admin).first()
    if admin_exists:
        return

    admin_username = os.environ.get("ADMIN_USERNAME", "VasyMinusov")
    admin_password = os.environ.get("ADMIN_PASSWORD", "0907Seva!!!2003")
    moderator_username = os.environ.get("MODERATOR_USERNAME", "moderator")
    moderator_password = os.environ.get("MODERATOR_PASSWORD", "moderato123")

    db.add(User(
        username=admin_username,
        email="admin@ctf-platform.localhost",
        password_hash=hash_password(admin_password),
        role=UserRole.admin,
    ))
    db.add(User(
        username=moderator_username,
        email="moderator@ctf-platform.localhost",
        password_hash=hash_password(moderator_password),
        role=UserRole.moderator,
    ))
    db.commit()
    print(f"[INIT] Создан дефолтный администратор: {admin_username}")
    print(f"[INIT] Создан дефолтный модератор: {moderator_username}")


@app.on_event("startup")
def on_startup():
    last_error = None
    for attempt in range(10):
        try:
            # 1. Bootstrap существующей «старой» БД: если в ней уже есть
            #    users, но нет alembic_version — стампим 0001_legacy, чтобы
            #    Alembic не пытался пересоздать legacy-таблицы.
            _bootstrap_legacy_db()

            # 2. Alembic upgrade head: создаёт всё, чего не хватает —
            #    на чистой БД и legacy-таблицы, и таблицы соревнований.
            _run_alembic_migrations()

            # 3. Исторические идемпотентные ALTER'ы — для очень старых БД.
            _run_legacy_ddl()

            last_error = None
            break
        except OperationalError as e:
            last_error = e
            time.sleep(2)
    if last_error is not None:
        raise last_error

    db = SessionLocal()
    try:
        _ensure_admin_exists(db)
        challenge_registry.sync_challenges(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}