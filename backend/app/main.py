import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from .routers import auth, challenges, admin, writeups, lessons
from .services import challenge_registry
from .models import User, UserRole
from .security import hash_password

app = FastAPI(title="CTF Training Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(challenges.router)
app.include_router(admin.router)
app.include_router(writeups.router)
app.include_router(lessons.router)


def _ensure_admin_exists(db: Session):
    """Создаёт дефолтного админа admin/admin123, если в БД ещё нет ни одного админа."""
    admin_exists = db.query(User).filter(User.role == UserRole.admin).first()
    if admin_exists:
        return
    default_admin = User(
        username="admin",
        email="admin@ctf-platform.localhost",
        password_hash=hash_password("admin123"),
        role=UserRole.admin,
    )
    db.add(default_admin)

    default_moderator = User(
        username="moderator",
        email="moderato@ctf-platform.localhost",
        password_hash=hash_password("moderato123"),
        role=UserRole.moderator,
    )
    db.add(default_moderator)
    db.commit()
    print("[INIT] Создан дефолтный администратор: admin / admin123")


def _run_migrations():
    """Лёгкие миграции для существующих БД: create_all не добавляет новые
    колонки в уже созданные таблицы, поэтому докидываем их вручную."""
    from sqlalchemy import text

    ddl = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


@app.on_event("startup")
def on_startup():
    last_error = None
    for attempt in range(10):
        try:
            Base.metadata.create_all(bind=engine)
            _run_migrations()
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

