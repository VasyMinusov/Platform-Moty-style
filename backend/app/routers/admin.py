from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Challenge, ChallengeInstance, User, UserRole
from ..schemas import UserOut, AdminUserUpdate, RoleUpdate
from ..security import require_admin, require_moderator
from ..services import challenge_registry, orchestrator

router = APIRouter(prefix="/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """
    Нормализовать datetime из БД в aware-UTC.

    Исторические записи в challenge_instances.expires_at / started_at
    сохранялись через datetime.utcnow() — это naive-объект (без tzinfo).
    При чтении из колонки TIMESTAMP WITHOUT TIME ZONE SQLAlchemy
    возвращает naive-datetime, а сравнение с datetime.now(UTC) падает
    с TypeError: can't compare offset-naive and offset-aware datetimes.

    Эта функция приводит любое значение к aware-UTC:
      - None          → None
      - naive         → naive.replace(tzinfo=UTC)  (считаем, что это UTC)
      - aware (любой) → astimezone(UTC)
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ═══════════════════════════════════════════════════════════════════════
# Challenges
# ═══════════════════════════════════════════════════════════════════════


@router.post("/challenges/sync")
def sync_challenges(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Пересканировать CHALLENGES_DIR и синхронизировать БД.
    Вызывайте после добавления новой папки-задания — код менять не нужно."""
    count = challenge_registry.sync_challenges(db)
    return {"synced": count}


# ═══════════════════════════════════════════════════════════════════════
# Управление пользователями
# ═══════════════════════════════════════════════════════════════════════


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_moderator),
):
    """Список пользователей платформы.
    Доступен админу и модератору (модератор — только просмотр)."""
    return db.query(User).order_by(User.id).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Выставить статус и/или заблокировать/разблокировать пользователя.
    Только админ. Нельзя блокировать себя и других администраторов."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if payload.status is not None:
        # Пустая строка — снять статус
        status_value = payload.status.strip().lstrip("#").strip()
        user.status = status_value or None

    if payload.is_blocked is not None:
        if payload.is_blocked:
            if user.id == admin.id:
                raise HTTPException(400, "You cannot block yourself")
            if user.role == UserRole.admin:
                raise HTTPException(400, "You cannot block an administrator")
        user.is_blocked = payload.is_blocked

    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}/role", response_model=UserOut)
def set_user_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Назначить роль пользователю (student / moderator / admin). Только админ."""
    try:
        new_role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(400, f"Unknown role: {payload.role}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and new_role != UserRole.admin:
        raise HTTPException(400, "You cannot demote yourself")

    user.role = new_role
    db.commit()
    db.refresh(user)
    return user


# ═══════════════════════════════════════════════════════════════════════
# Instances
# ═══════════════════════════════════════════════════════════════════════


def _client_host(request: Request) -> str:
    """
    Хост для формирования URL инстансов.

    Если студент открыл платформу с 192.168.1.5 — контейнер показываем
    как http://192.168.1.5:30001, а не 127.0.0.1:30001.
    Приоритет: X-Forwarded-Host (за nginx) → Host → localhost.
    """
    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        forwarded = forwarded.split(",")[0].strip()
    host = forwarded or request.headers.get("host", "")
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host or "localhost"


@router.get("/instances")
def admin_list_instances(
    request: Request,
    only_alive: bool = Query(
        False,
        description="Проверить каждый контейнер через docker inspect.",
    ),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
) -> dict:
    """
    Все running-инстансы платформы.

    Возвращает: {items: [...], total: N}. Каждый item содержит
    id, user_id, username, challenge_slug, challenge_title, container_id,
    host_port, url, status, started_at, expires_at, is_expired, is_alive.

    FIX: expires_at / started_at из БД могут быть naive (исторические
    записи через datetime.utcnow()). Перед сравнением с now(UTC)
    нормализуем их через _as_aware_utc, иначе TypeError → 500.
    """
    rows = (
        db.query(ChallengeInstance)
        .filter(ChallengeInstance.status == "running")
        .order_by(ChallengeInstance.started_at.desc())
        .all()
    )

    host = _client_host(request)
    now = datetime.now(UTC)
    items: list[dict] = []

    # Кеши: чтобы не дёргать БД на каждую строку.
    user_cache: dict[int, str] = {}
    ch_cache: dict[int, tuple[str, str]] = {}

    for inst in rows:
        username = user_cache.get(inst.user_id)
        if username is None:
            u = db.query(User).filter(User.id == inst.user_id).first()
            username = u.username if u else "?"
            user_cache[inst.user_id] = username

        cached = ch_cache.get(inst.challenge_id)
        if cached is None:
            ch = (
                db.query(Challenge)
                .filter(Challenge.id == inst.challenge_id)
                .first()
            )
            if not ch:
                continue
            cached = (ch.slug, ch.title)
            ch_cache[inst.challenge_id] = cached
        ch_slug, ch_title = cached

        # FIX: нормализуем naive → aware UTC перед сравнением с now.
        started_at_utc = _as_aware_utc(inst.started_at)
        expires_at_utc = _as_aware_utc(inst.expires_at)

        is_alive: bool | None = None
        if only_alive:
            # FIX: container_id может быть None (инстанс без контейнера —
            # например, status='running' в БД, но контейнер уже удалён).
            # Пустая строка → orchestrator.is_container_alive вернёт False,
            # не бросая исключение.
            try:
                is_alive = orchestrator.is_container_alive(inst.container_id or "")
            except Exception:
                # Любая ошибка Docker (APIError и т.п.) — считаем контейнер
                # мёртвым, но эндпоинт не роняем.
                is_alive = False
            if is_alive is False:
                continue

        items.append({
            "id": inst.id,
            "user_id": inst.user_id,
            "username": username,
            "challenge_id": inst.challenge_id,
            "challenge_slug": ch_slug,
            "challenge_title": ch_title,
            "container_id": inst.container_id,
            "host_port": inst.host_port,
            "url": f"http://{host}:{inst.host_port}",
            "status": inst.status,
            "started_at": started_at_utc.isoformat() if started_at_utc else None,
            "expires_at": expires_at_utc.isoformat() if expires_at_utc else None,
            "is_expired": expires_at_utc < now if expires_at_utc else False,
            "is_alive": is_alive,
        })

    return {"items": items, "total": len(items)}


@router.post("/instances/{instance_id}/stop")
def admin_stop_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
) -> dict:
    """Остановить один контейнер. 404 если нет, 409 если уже не running."""
    inst = (
        db.query(ChallengeInstance)
        .filter(ChallengeInstance.id == instance_id)
        .first()
    )
    if not inst:
        raise HTTPException(404, "Instance not found")
    if inst.status != "running":
        raise HTTPException(409, f"Instance is not running (status={inst.status})")

    orchestrator.stop_instance(db, inst)
    return {"stopped": 1, "instance_id": instance_id}


@router.post("/instances/stop-all")
def admin_stop_all_instances(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
) -> dict:
    """
    Остановить ВСЕ running-инстансы. Идемпотентно.

    Каждая остановка в try/except: если контейнер уже удалён из Docker —
    продолжаем, не роняем весь запрос. В ответе stopped/failed/total.
    """
    instances = (
        db.query(ChallengeInstance)
        .filter(ChallengeInstance.status == "running")
        .all()
    )

    stopped = 0
    failed = 0
    for inst in instances:
        try:
            orchestrator.stop_instance(db, inst)
            stopped += 1
        except Exception:
            failed += 1

    return {"stopped": stopped, "failed": failed, "total": len(instances)}


@router.post("/instances/reap")
def reap_expired(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Ручной запуск очистки просроченных контейнеров
    (в проде лучше вызывать по расписанию, например APScheduler)."""
    count = orchestrator.reap_expired(db)
    return {"stopped": count}