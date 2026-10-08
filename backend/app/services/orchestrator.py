"""Оркестратор: управляет жизненным циклом контейнеров заданий через Docker API.

Поддерживает два режима:
- глобальные задания (Challenge) — сеть settings.docker_network, порты из общего диапазона;
- задания соревнования (CompetitionChallenge) — отдельная сеть ctf-comp-{slug}_net,
  порты из port_range_start/end соревнования.

Docker-клиент создаётся лениво: на этапе docker build сокет недоступен,
поэтому импорт модуля не должен падать.
"""
import hashlib
import socket
import threading
from contextlib import closing
from datetime import datetime, timedelta

import docker
from docker.errors import NotFound
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Challenge, ChallengeInstance
from ..models_competitions import Competition, CompetitionChallenge
from . import challenge_registry as registry
from .competition_network import network_name as comp_network_name


_docker_client = None


def _get_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# Сборка образов и выбор порта — критическая секция.
_port_lock = threading.Lock()

_build_lock = threading.Lock()
_built_tags: set[str] = set()


# ══════════════════════════════════════════════════════════════════════
# Порты
# ══════════════════════════════════════════════════════════════════════

def _ports_in_use(db: Session) -> set[int]:
    """Все порты, занятые running-инстансами (глобальные и соревновательные)."""
    rows = (
        db.query(ChallengeInstance.host_port)
        .filter(ChallengeInstance.status == "running")
        .all()
    )
    return {row[0] for row in rows if row[0] is not None}


def _free_port_in_range(db: Session, start: int, end: int) -> int:
    reserved = _ports_in_use(db)
    for port in range(start, end + 1):
        if port in reserved:
            continue
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Нет свободных портов для нового задания")


def _free_port(db: Session) -> int:
    return _free_port_in_range(
        db,
        settings.challenge_port_range_start,
        settings.challenge_port_range_end,
    )


# ══════════════════════════════════════════════════════════════════════
# Общие лимиты контейнера
# ══════════════════════════════════════════════════════════════════════

def _common_container_kwargs() -> dict:
    return {
        "detach": True,
        "mem_limit": "256m",
        "nano_cpus": 500_000_000,  # 0.5 CPU
        "security_opt": ["no-new-privileges"],
        "cap_drop": ["ALL"],
        "pids_limit": 128,
        "ulimits": [
            docker.types.Ulimit(name="nofile", soft=1024, hard=2048),
            docker.types.Ulimit(name="nproc", soft=128, hard=256),
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# Глобальные задания (обратная совместимость)
# ══════════════════════════════════════════════════════════════════════

def ensure_image_built(challenge: Challenge) -> str:
    tag = registry.image_tag_for(challenge.slug)
    if tag in _built_tags:
        return tag
    with _build_lock:
        if tag in _built_tags:
            return tag
        context = registry.build_context_for(challenge.slug)
        _get_client().images.build(path=context, tag=tag, rm=True)
        _built_tags.add(tag)
    return tag


def _container_is_alive(container_id: str) -> bool:
    try:
        container = _get_client().containers.get(container_id)
    except NotFound:
        return False
    return container.status in ("running", "created", "restarting")


def start_instance(db: Session, user_id: int, challenge: Challenge) -> ChallengeInstance:
    existing = (
        db.query(ChallengeInstance)
        .filter_by(user_id=user_id, challenge_id=challenge.id, competition_id=None)
        .first()
    )
    if existing and existing.status == "running" and _container_is_alive(existing.container_id):
        return existing

    tag = ensure_image_built(challenge)

    with _port_lock:
        host_port = _free_port(db)
        container = _get_client().containers.run(
            tag,
            ports={f"{challenge.container_port}/tcp": host_port},
            network=settings.docker_network,
            labels={"ctf-user": str(user_id), "ctf-challenge": challenge.slug},
            **_common_container_kwargs(),
        )

        expires_at = datetime.utcnow() + timedelta(seconds=settings.instance_ttl_seconds)
        if existing:
            if existing.container_id and existing.container_id != container.id:
                try:
                    _get_client().containers.get(existing.container_id).remove(force=True)
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
        container = _get_client().containers.get(instance.container_id)
        container.stop(timeout=5)
        container.remove(force=True)
    except NotFound:
        pass
    instance.status = "stopped"
    db.commit()


# ══════════════════════════════════════════════════════════════════════
# Задания соревнования
# ══════════════════════════════════════════════════════════════════════

def _comp_container_is_alive(container_id: str) -> bool:
    try:
        c = _get_client().containers.get(container_id)
    except NotFound:
        return False
    return c.status in ("running", "created", "restarting")


def _ensure_comp_image(ch_comp: CompetitionChallenge, comp: Competition) -> str:
    from .competition_challenge_service import image_tag
    tag = image_tag(comp.slug, ch_comp.slug)
    if tag in _built_tags:
        return tag
    try:
        _get_client().images.get(tag)
        _built_tags.add(tag)
        return tag
    except NotFound:
        raise RuntimeError(
            f"Image {tag} not found. Build the challenge first."
        )


def _validate_challenge_port(ch_comp: CompetitionChallenge) -> int:
    if ch_comp.container_port is None:
        raise RuntimeError("Challenge has no container_port")
    from .competition_manifest import RESERVED_PORTS
    if ch_comp.container_port in RESERVED_PORTS:
        raise RuntimeError(
            f"container_port {ch_comp.container_port} is reserved by platform"
        )
    if not (1 <= ch_comp.container_port <= 65535):
        raise RuntimeError(f"container_port out of range: {ch_comp.container_port}")
    return ch_comp.container_port


def start_competition_instance(
    db: Session,
    comp: Competition,
    ch_comp: CompetitionChallenge,
    *,
    user_id: int,
    team_id: int | None,
) -> ChallengeInstance:
    """Запускает инстанс задания соревнования.

    Ключ: (competition_id, challenge_id, user_id) или
          (competition_id, challenge_id, team_id).
    Сеть: ctf-comp-{comp.slug}_net.
    Порты: из comp.port_range_start/port_range_end.
    """
    if comp.port_range_start is None or comp.port_range_end is None:
        raise RuntimeError("Competition has no port range allocated")

    container_port = _validate_challenge_port(ch_comp)

    # Ищем существующий инстанс по ключу.
    q = db.query(ChallengeInstance).filter_by(
        competition_id=comp.id,
        challenge_id=ch_comp.id,
    )
    if team_id is not None:
        q = q.filter_by(team_id=team_id)
    else:
        q = q.filter_by(user_id=user_id)

    existing = q.first()
    if existing and existing.status == "running" and _comp_container_is_alive(existing.container_id):
        return existing

    tag = _ensure_comp_image(ch_comp, comp)

    # Проверка лимитов.
    _ensure_instance_limits(db, comp, user_id=user_id, team_id=team_id)

    with _port_lock:
        host_port = _free_port_in_range(db, comp.port_range_start, comp.port_range_end)

        # Динамический флаг.
        from .competition_dynamic_flags import generate_dynamic_flag
        dynamic_flag = None
        strategy = (
            ch_comp.dynamic_flag_strategy.value
            if hasattr(ch_comp.dynamic_flag_strategy, "value")
            else str(ch_comp.dynamic_flag_strategy)
        )
        if strategy and strategy != "static":
            dynamic_flag = generate_dynamic_flag(
                ch_comp, comp, user_id=user_id, team_id=team_id,
            )

        env: dict[str, str] = {}
        if dynamic_flag:
            env["FLAG"] = dynamic_flag
            env["CTF_FLAG"] = dynamic_flag

        container = _get_client().containers.run(
            tag,
            ports={f"{container_port}/tcp": host_port},
            network=comp_network_name(comp.slug),
            environment=env or None,
            labels={
                "ctf-user": str(user_id),
                "ctf-competition": comp.slug,
                "ctf-challenge": ch_comp.slug,
                "ctf-team": str(team_id) if team_id is not None else "",
            },
            **_common_container_kwargs(),
        )

        ttl = comp.instance_ttl_seconds or settings.instance_ttl_seconds
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)

        dynamic_hash = (
            hashlib.sha256(dynamic_flag.encode("utf-8")).hexdigest()
            if dynamic_flag else None
        )

        if existing:
            if existing.container_id and existing.container_id != container.id:
                try:
                    _get_client().containers.get(existing.container_id).remove(force=True)
                except NotFound:
                    pass
            existing.container_id = container.id
            existing.host_port = host_port
            existing.status = "running"
            existing.started_at = datetime.utcnow()
            existing.expires_at = expires_at
            existing.competition_id = comp.id
            existing.team_id = team_id
            existing.challenge_kind = ch_comp.kind.value
            if dynamic_hash:
                existing.dynamic_flag_hash = dynamic_hash
            instance = existing
        else:
            instance = ChallengeInstance(
                user_id=user_id,
                challenge_id=ch_comp.id,
                container_id=container.id,
                host_port=host_port,
                status="running",
                expires_at=expires_at,
                competition_id=comp.id,
                team_id=team_id,
                challenge_kind=ch_comp.kind.value,
                dynamic_flag_hash=dynamic_hash,
            )
            db.add(instance)

        db.commit()
        db.refresh(instance)
        return instance


def stop_competition_instance(db: Session, instance: ChallengeInstance) -> None:
    """Останавливает контейнер соревновательного инстанса."""
    stop_instance(db, instance)


def stop_all_for_competition(db: Session, competition_id: int) -> int:
    """Останавливает все инстансы соревнования (при finish/cancel)."""
    instances = (
        db.query(ChallengeInstance)
        .filter_by(competition_id=competition_id, status="running")
        .all()
    )
    for inst in instances:
        try:
            stop_instance(db, inst)
        except Exception:
            pass
    return len(instances)


# ══════════════════════════════════════════════════════════════════════
# Лимиты
# ══════════════════════════════════════════════════════════════════════

def _ensure_instance_limits(
    db: Session,
    comp: Competition,
    *,
    user_id: int,
    team_id: int | None,
) -> None:
    running = (
        db.query(ChallengeInstance)
        .filter(
            ChallengeInstance.competition_id == comp.id,
            ChallengeInstance.status == "running",
        )
    )

    if comp.max_instances_per_competition is not None:
        total = running.count()
        if total >= comp.max_instances_per_competition:
            raise RuntimeError("Competition instance limit reached")

    if team_id is not None and comp.max_instances_per_team is not None:
        per_team = running.filter(ChallengeInstance.team_id == team_id).count()
        if per_team >= comp.max_instances_per_team:
            raise RuntimeError("Team instance limit reached")

    if team_id is None and comp.max_instances_per_user is not None:
        per_user = running.filter(ChallengeInstance.user_id == user_id).count()
        if per_user >= comp.max_instances_per_user:
            raise RuntimeError("User instance limit reached")


# ══════════════════════════════════════════════════════════════════════
# Reaper
# ══════════════════════════════════════════════════════════════════════

def reap_expired(db: Session) -> int:
    """Останавливает все инстансы (глобальные и соревновательные)
    с истёкшим TTL."""
    now = datetime.utcnow()
    expired = (
        db.query(ChallengeInstance)
        .filter(
            ChallengeInstance.status == "running",
            ChallengeInstance.expires_at < now,
        )
        .all()
    )
    for instance in expired:
        try:
            stop_instance(db, instance)
        except Exception:
            pass
    return len(expired)