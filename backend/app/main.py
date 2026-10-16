import os
import time

import httpx
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


# ══════════════════════════════════════════════════════════════════════
# Alembic
# ══════════════════════════════════════════════════════════════════════

def _alembic_config():
    """Возвращает Config для Alembic или None, если alembic.ini не найден."""
    from alembic.config import Config

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(backend_root, "alembic.ini")
    if not os.path.exists(cfg_path):
        return None

    cfg = Config(cfg_path)
    cfg.set_main_option("script_location", os.path.join(backend_root, "alembic"))
    return cfg


def _bootstrap_legacy_db():
    """
    Если в БД уже есть таблица users, но нет alembic_version — значит
    БД создана старым create_all. Стампим её первой ревизией.
    """
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
    """alembic upgrade head."""
    from alembic import command

    cfg = _alembic_config()
    if cfg is None:
        print("[INIT] alembic.ini не найден — пропускаю Alembic-миграции")
        return

    command.upgrade(cfg, "head")


def _run_legacy_ddl():
    """Исторические идемпотентные ALTER'ы для очень старых БД."""
    from sqlalchemy import text

    ddl = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


# ══════════════════════════════════════════════════════════════════════
# Bootstrap первых пользователей через auth-service
# ══════════════════════════════════════════════════════════════════════

# Сколько раз пытаться зарегистрировать пользователя в auth-service,
# если запрос падает не с 409 (email/username занят).
#
# Зачем retry:
#   - На холодном старте auth-service может ещё не закончить прогрев
#     (Argon2 init, БД-пул), и первый POST вернёт 500/503.
#   - Если HIBP недоступен и fail_open=false — register падает. Но
#     в нашем compose fail_open=true.
#   - Если валидация email провалилась — retry не поможет, но лог
#     покажет причину.
_BOOTSTRAP_REGISTER_MAX_ATTEMPTS = 3
_BOOTSTRAP_REGISTER_DELAY_SECONDS = 2.0


def _wait_for_auth_service(max_attempts: int = 30, delay: float = 2.0) -> bool:
    """
    Ждём, пока auth-service ответит на /health/live.

    Возвращает True, если дождались; False — если таймаут.
    Логирует прогресс каждые 5 попыток (чтобы не спамить).
    """
    url = f"{settings.auth_service_url}/health/live"
    for attempt in range(1, max_attempts + 1):
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code == 200:
                print(f"[INIT] auth-service готов (попытка {attempt})")
                return True
        except httpx.HTTPError:
            pass

        # Логируем каждые 5 попыток, чтобы видеть прогресс, но не спамить.
        if attempt == 1 or attempt % 5 == 0:
            print(f"[INIT] ожидание auth-service ({attempt}/{max_attempts})…")
        time.sleep(delay)

    print(f"[INIT] auth-service не ответил за {max_attempts * delay:.0f} секунд")
    return False


def _register_or_login_in_auth_service(
    username: str,
    email: str,
    password: str,
) -> dict | None:
    """
    Регистрирует пользователя в auth-service или логинит, если уже
    существует. Возвращает профиль (dict с id, username, email) или None.

    Стратегия:
      1. POST /api/v1/auth/register.
         - 201 — новый пользователь, возвращаем профиль.
         - 409 — email/username занят → идём в login.
         - 5xx — retry (до _BOOTSTRAP_REGISTER_MAX_ATTEMPTS раз).
         - 4xx (кроме 409) — ошибка конфигурации (например, 422 на
           email), логируем и выходим без retry.
      2. POST /api/v1/auth/login по email.
         - 200 — возвращаем access_token + идём в /users/me за id.
         - 401 — пароль не совпадает. Не пытаемся восстановиться:
           админ должен руками разобраться, чем занят этот email.
         - mfa_required=true — bootstrap невозможен из скрипта.
    """
    base = settings.auth_service_url

    # ── 1. Пробуем зарегистрировать ────────────────────────────────
    last_error: str | None = None

    for attempt in range(1, _BOOTSTRAP_REGISTER_MAX_ATTEMPTS + 1):
        try:
            r = httpx.post(
                f"{base}/api/v1/auth/register",
                json={"username": username, "email": email, "password": password},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            last_error = f"сетевая ошибка: {exc}"
            print(
                f"[INIT] register attempt {attempt}: {last_error}; "
                f"retry через {_BOOTSTRAP_REGISTER_DELAY_SECONDS}s"
            )
            time.sleep(_BOOTSTRAP_REGISTER_DELAY_SECONDS)
            continue

        # ── Успех ─────────────────────────────────────────────────
        if r.status_code == 201:
            return r.json()

        # ── Уже существует → login ────────────────────────────────
        if r.status_code == 409:
            break  # выходим из retry-loop, идём в login

        # ── Транзиентная ошибка 5xx → retry ──────────────────────
        if r.status_code >= 500:
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            print(
                f"[INIT] register attempt {attempt}: {last_error}; "
                f"retry через {_BOOTSTRAP_REGISTER_DELAY_SECONDS}s"
            )
            time.sleep(_BOOTSTRAP_REGISTER_DELAY_SECONDS)
            continue

        # ── Осмысленная 4xx (422 — email не валиден, 400 — что-то ещё) ──
        # Retry не поможет. Логируем причину.
        print(
            f"[INIT] register вернул HTTP {r.status_code}: {r.text[:500]}\n"
            f"[INIT] ПРОВЕРЬ: ADMIN_EMAIL/MODERATOR_EMAIL в .env.\n"
            f"[INIT] Pydantic EmailStr отвергает .localhost / .test / "
            f".invalid / .example / .onion — используй .internal."
        )
        return None

    else:
        # Retry-цикл исчерпан, не вышли ни в 201, ни в 409
        if last_error:
            print(f"[INIT] register исчерпал попытки: {last_error}")
        return None

    # ── 2. Уже существует → логинимся по email ─────────────────────
    try:
        lr = httpx.post(
            f"{base}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        print(f"[INIT] login: сетевая ошибка: {exc}")
        return None

    if lr.status_code != 200:
        print(f"[INIT] login вернул HTTP {lr.status_code}: {lr.text[:200]}")
        return None

    body = lr.json()

    # ── MFA включён у bootstrap-пользователя ───────────────────────
    # Из скрипта MFA не пройти. Просим оператора разобраться руками.
    if body.get("mfa_required"):
        print(
            f"[INIT] {email} требует MFA — bootstrap невозможен. "
            "Сбросьте MFA через auth-service (users/me/mfa/disable) "
            "или используйте другой аккаунт."
        )
        return None

    token = body.get("access_token")
    if not token:
        print(f"[INIT] login не вернул access_token: {body}")
        return None

    # ── 3. Профиль ─────────────────────────────────────────────────
    try:
        mr = httpx.get(
            f"{base}/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        print(f"[INIT] /users/me: сетевая ошибка: {exc}")
        return None

    if mr.status_code != 200:
        print(f"[INIT] /users/me вернул HTTP {mr.status_code}")
        return None
    return mr.json()


def _ensure_bootstrap_users(db: Session):
    """
    Создаёт admin и moderator в auth-service (если их нет) и в локальной
    БД. Идемпотентно: при повторных запусках ничего не делает.

    Порядок:
      1. Проверяем, есть ли локальный admin.
      2. Если нет — ждём auth-service, регистрируем admin+moderator,
         создаём локальные записи с тем же id.
    """
    has_admin = db.query(User).filter(User.role == UserRole.admin).first()
    if has_admin:
        return

    print("[INIT] Bootstrap: admin/moderator отсутствуют, регистрирую в auth-service")
    if not _wait_for_auth_service():
        print(
            "[INIT] auth-service не отвечает — пропускаю bootstrap. "
            "Перезапустите backend после того, как auth-service поднимется."
        )
        return

    # ── admin ─────────────────────────────────────────────────────
    profile = _register_or_login_in_auth_service(
        settings.admin_username,
        settings.admin_email,
        settings.admin_password,
    )
    if profile:
        # Проверка на коллизию id: если в локальной БД уже есть User
        # с таким же id (например, кто-то уже создал запись при lazy
        # provisioning), не будем пересоздавать.
        existing = db.query(User).filter(User.id == profile["id"]).first()
        if existing:
            print(
                f"[INIT] admin: User с id={profile['id']} уже существует "
                f"({existing.username}); обновляю role на admin"
            )
            existing.role = UserRole.admin
        else:
            db.add(User(
                id=profile["id"],
                username=profile["username"],
                email=profile["email"],
                role=UserRole.admin,
                points=0,
                is_blocked=False,
            ))
        print(f"[INIT] admin создан: {profile['username']} (id={profile['id']})")
    else:
        print("[INIT] admin НЕ создан — см. логи выше")

    # ── moderator ─────────────────────────────────────────────────
    profile = _register_or_login_in_auth_service(
        settings.moderator_username,
        settings.moderator_email,
        settings.moderator_password,
    )
    if profile:
        existing = db.query(User).filter(User.id == profile["id"]).first()
        if existing:
            print(
                f"[INIT] moderator: User с id={profile['id']} уже существует "
                f"({existing.username}); обновляю role на moderator"
            )
            existing.role = UserRole.moderator
        else:
            db.add(User(
                id=profile["id"],
                username=profile["username"],
                email=profile["email"],
                role=UserRole.moderator,
                points=0,
                is_blocked=False,
            ))
        print(f"[INIT] moderator создан: {profile['username']} (id={profile['id']})")
    else:
        print("[INIT] moderator НЕ создан — см. логи выше")

    db.commit()


# ══════════════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def on_startup():
    last_error = None
    for attempt in range(10):
        try:
            _bootstrap_legacy_db()
            _run_alembic_migrations()
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
        _ensure_bootstrap_users(db)
        challenge_registry.sync_challenges(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}