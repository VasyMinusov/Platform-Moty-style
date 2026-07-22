"""
Оркестратор: управляет жизненным циклом контейнеров заданий через Docker API.

Встроенные меры безопасности при запуске:
- отдельная изолированная сеть (isolated_net), без доступа к platform_net (backend/db);
- лимиты CPU/RAM на контейнер;
- cap_drop ALL + no-new-privileges;
- автоматическое удаление по истечении TTL (см. reap_expired).
"""
import socket
import threading
from contextlib import closing
from datetime import datetime, timedelta

import docker
from docker.errors import NotFound
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Challenge, ChallengeInstance
from . import challenge_registry as registry

_client = docker.from_env()

# Сборка образов и выбор порта для нового инстанса — критическая секция.
# FastAPI выполняет sync-эндпоинты в пуле потоков, поэтому два студента,
# нажавшие "Запустить" одновременно, могут попасть в start_instance
# параллельно. Раньше порт выбирался только проверкой "слушает ли кто-то
# 127.0.0.1:port прямо сейчас" — между этой проверкой и реальным стартом
# контейнера был race window, из-за которого второй запрос мог схватить
# уже занятый (но ещё не забинденный) порт и упасть с ошибкой Docker
# "port is already allocated". Лочим выбор порта + создание контейнера
# одним мьютексом на процесс — этого достаточно, т.к. backend работает в
# один воркер (см. backend/Dockerfile). Если перейдёте на несколько
# воркеров/реплик backend — замените Lock на pg_advisory_lock в БД.
_port_lock = threading.Lock()

# Образы собираются лениво при первом запуске задания. Кэшируем, какие
# теги уже собраны в рамках текущего процесса, чтобы конкурентные запросы
# разных студентов на один и тот же челлендж не запускали `docker build`
# параллельно и не гоняли пересборку на каждый /start повторно.
_build_lock = threading.Lock()
_built_tags: set[str] = set()


def _ports_in_use(db: Session) -> set[int]:
    """Порты, занятые по данным БД (инстансы со статусом running).
    Дополняет OS-level проверку и защищает от гонки, когда контейнер уже
    создан, но ещё не успел забиндить порт на момент следующего запроса."""
    rows = db.query(ChallengeInstance.host_port).filter_by(status="running").all()
    return {row[0] for row in rows}


def _free_port(db: Session) -> int:
    reserved = _ports_in_use(db)
    for port in range(settings.challenge_port_range_start, settings.challenge_port_range_end + 1):
        if port in reserved:
            continue
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            # Docker публикует порты на 0.0.0.0, поэтому проверяем ВСЕ интерфейсы,
            # а не только loopback. Иначе orphan-контейнер или внешний слушатель
            # на 0.0.0.0 останется незамеченным и docker выдаст
            # "Bind for 0.0.0.0:<port> failed: port is already allocated".
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Нет свободных портов для нового задания")


def ensure_image_built(challenge: Challenge) -> str:
    tag = registry.image_tag_for(challenge.slug)
    if tag in _built_tags:
        return tag
    with _build_lock:
        if tag in _built_tags:
            return tag
        context = registry.build_context_for(challenge.slug)
        _client.images.build(path=context, tag=tag, rm=True)
        _built_tags.add(tag)
    return tag


def _container_is_alive(container_id: str) -> bool:
    try:
        container = _client.containers.get(container_id)
    except NotFound:
        return False
    return container.status in ("running", "created", "restarting")


def start_instance(db: Session, user_id: int, challenge: Challenge) -> ChallengeInstance:
    # Ищем ЛЮБОЙ инстанс этого пользователя для этого задания, а не только
    # "running" — в таблице действует UniqueConstraint(user_id, challenge_id),
    # поэтому если раньше уже был запуск (и он остановлен/истёк), запись уже
    # существует. Раньше код всегда пытался вставить НОВУЮ строку — это
    # гарантированно падало с IntegrityError при повторном запуске того же
    # задания тем же пользователем (например, сразу после автоостановки по
    # факту решения). Теперь существующая запись переиспользуется (upsert).
    existing = (
        db.query(ChallengeInstance)
        .filter_by(user_id=user_id, challenge_id=challenge.id)
        .first()
    )
    if existing and existing.status == "running" and _container_is_alive(existing.container_id):
        return existing

    tag = ensure_image_built(challenge)

    with _port_lock:
        host_port = _free_port(db)
        container = _client.containers.run(
            tag,
            detach=True,
            ports={f"{challenge.container_port}/tcp": host_port},
            network=settings.docker_network,
            mem_limit="256m",
            nano_cpus=500_000_000,  # 0.5 CPU
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            labels={"ctf-user": str(user_id), "ctf-challenge": challenge.slug},
        )

        expires_at = datetime.utcnow() + timedelta(seconds=settings.instance_ttl_seconds)
        if existing:
            # Переиспользуем строку: старый (уже неактуальный) container_id
            # подчищаем на всякий случай перед тем, как затереть его.
            if existing.container_id and existing.container_id != container.id:
                try:
                    _client.containers.get(existing.container_id).remove(force=True)
                except NotFound:
                    pass
            existing.container_id = container.id
            existing.host_port = host_port
            existing.status = "running"
            existing.started_at = datetime.utcnow()
            existing.expires_at = expires_at
            instance = existing
        else:
            instance = ChallengeInstance(
                user_id=user_id,
                challenge_id=challenge.id,
                container_id=container.id,
                host_port=host_port,
                status="running",
                expires_at=expires_at,
            )
            db.add(instance)
        db.commit()
        db.refresh(instance)
        return instance


def stop_instance(db: Session, instance: ChallengeInstance) -> None:
    try:
        container = _client.containers.get(instance.container_id)
        container.stop(timeout=5)
        container.remove(force=True)
    except NotFound:
        pass
    instance.status = "stopped"
    db.commit()


def reap_expired(db: Session) -> int:
    """Останавливает все инстансы с истёкшим TTL. Вызывайте по расписанию
    (APScheduler / cron / фоновая задача) — работает одинаково для любых заданий."""
    now = datetime.utcnow()
    expired = (
        db.query(ChallengeInstance)
        .filter(ChallengeInstance.status == "running", ChallengeInstance.expires_at < now)
        .all()
    )
    for instance in expired:
        stop_instance(db, instance)
    return len(expired)