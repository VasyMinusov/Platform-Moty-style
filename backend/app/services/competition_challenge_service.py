"""Сервис заданий соревнования: загрузка ZIP, CRUD, сборка, промоушен.

Docker-клиент создаётся лениво, чтобы импорт модуля не падал на этапе
docker build (нет сокета). Сборка идёт через hardening: network=none,
allowlist базовых образов, проверка Dockerfile на опасные инструкции,
лимиты CPU/RAM.
"""
import hashlib
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import docker
from docker.errors import BuildError, DockerException, NotFound
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import Challenge as GlobalChallenge, User, UserRole
from ..models_competitions import (
    BuildStatus,
    ChallengeDifficulty,
    ChallengeKind,
    ChallengeType,
    ChallengeVisibility,
    Competition,
    CompetitionChallenge,
    CompetitionChallengeFile,
    CompetitionSolve,
    DynamicFlagStrategy,
)
from ..schemas_competitions import CompetitionChallengeUpdate
from . import competition_audit
from . import competition_build_security
from .competition_manifest import parse_zip


_docker_client = None


def _get_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# Сборка образов — критическая секция. Лочим, чтобы две конкурентные
# загрузки не запускали docker build параллельно.
_build_lock = threading.Lock()
_built_tags: set[str] = set()


# ══════════════════════════════════════════════════════════════════════
# Пути
# ══════════════════════════════════════════════════════════════════════

def _competition_root(comp_slug: str) -> Path:
    root = Path(settings.challenges_dir) / settings.competitions_subdir / comp_slug
    root.mkdir(parents=True, exist_ok=True)
    return root


def challenge_root(comp_slug: str, ch_slug: str) -> Path:
    root = _competition_root(comp_slug) / ch_slug
    root.mkdir(parents=True, exist_ok=True)
    return root


def image_tag(comp_slug: str, ch_slug: str) -> str:
    return f"ctf-comp-{comp_slug}-{ch_slug}:latest"


# ══════════════════════════════════════════════════════════════════════
# Список / чтение
# ══════════════════════════════════════════════════════════════════════

def list_challenges(
    db: Session,
    comp: Competition,
    *,
    include_disabled: bool = False,
    include_hidden: bool = False,
) -> list[CompetitionChallenge]:
    q = db.query(CompetitionChallenge).filter_by(competition_id=comp.id)
    if not include_disabled:
        q = q.filter(CompetitionChallenge.enabled.is_(True))
    if not include_hidden:
        q = q.filter(CompetitionChallenge.visibility != ChallengeVisibility.hidden)
    return q.order_by(
        CompetitionChallenge.order_index,
        CompetitionChallenge.id,
    ).all()


def get_challenge(db: Session, comp: Competition, ch_slug: str) -> CompetitionChallenge:
    ch = (
        db.query(CompetitionChallenge)
        .filter_by(competition_id=comp.id, slug=ch_slug)
        .first()
    )
    if not ch:
        raise HTTPException(404, "Challenge not found")
    return ch


def is_solved_by(
    db: Session, ch: CompetitionChallenge, *,
    user_id: Optional[int], team_id: Optional[int],
) -> bool:
    q = db.query(CompetitionSolve).filter_by(challenge_id=ch.id)
    if team_id is not None:
        q = q.filter(CompetitionSolve.team_id == team_id)
    elif user_id is not None:
        q = q.filter(CompetitionSolve.user_id == user_id)
    else:
        return False
    return q.first() is not None


# ══════════════════════════════════════════════════════════════════════
# Загрузка ZIP
# ══════════════════════════════════════════════════════════════════════

def _read_upload(upload: UploadFile) -> bytes:
    max_bytes = settings.competition_zip_max_bytes
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"ZIP exceeds {max_bytes} bytes")
    return data


async def upload_zip(
    db: Session,
    comp: Competition,
    upload: UploadFile,
    actor: User,
) -> CompetitionChallenge:
    """Принимает ZIP, распаковывает в
    {challenges_dir}/competitions/{comp_slug}/{ch_slug}, создаёт/обновляет
    CompetitionChallenge и запускает сборку образа в фоне (kind=docker).
    """
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Expected a .zip file")

    zip_bytes = _read_upload(upload)

    # Распаковка во временную папку — чтобы не портить существующее
    # задание до полной валидации.
    tmp_dir = _competition_root(comp.slug) / ".incoming" / uuid.uuid4().hex
    try:
        parsed = parse_zip(zip_bytes, tmp_dir)
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(400, f"Failed to parse ZIP: {e}")

    slug = parsed.slug
    manifest = parsed.manifest

    existing = (
        db.query(CompetitionChallenge)
        .filter_by(competition_id=comp.id, slug=slug)
        .first()
    )

    # Переносим распакованное содержимое в final, заменив старое.
    final_dir = challenge_root(comp.slug, slug)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.move(str(tmp_dir), str(final_dir))
    incoming_parent = _competition_root(comp.slug) / ".incoming"
    try:
        incoming_parent.rmdir()
    except OSError:
        pass

    # ── Валидация Dockerfile для kind=docker ──────────────────────────
    if manifest.kind == "docker":
        dockerfile_rel = (
            manifest.metadata.get("docker", {}).get("dockerfile_path", "Dockerfile")
            if isinstance(manifest.metadata, dict)
            else "Dockerfile"
        )
        dockerfile_path = final_dir / dockerfile_rel
        if not dockerfile_path.exists():
            dockerfile_path = final_dir / "Dockerfile"
        try:
            competition_build_security.validate_dockerfile(dockerfile_path)
        except HTTPException:
            shutil.rmtree(final_dir, ignore_errors=True)
            raise

    # Флаг — хэшируем; манифест может содержать flag или flag_hash.
    flag_hash = manifest.flag_hash
    if not flag_hash and manifest.flag:
        flag_hash = hashlib.sha256(manifest.flag.encode("utf-8")).hexdigest()

    # Создаём или обновляем CompetitionChallenge.
    if existing is None:
        ch = CompetitionChallenge(
            competition_id=comp.id,
            slug=slug,
            title=manifest.title,
            uploaded_by=actor.id,
        )
        db.add(ch)
        db.flush()
    else:
        ch = existing
        db.query(CompetitionChallengeFile).filter_by(challenge_id=ch.id).delete()

    ch.title = manifest.title
    ch.kind = ChallengeKind(manifest.kind)
    ch.type = ChallengeType(manifest.type)
    ch.category = manifest.category
    ch.difficulty = manifest.difficulty
    ch.description_md = manifest.description
    ch.points = manifest.points
    ch.flag_hash = flag_hash
    ch.dynamic_flag_strategy = DynamicFlagStrategy(manifest.dynamic_flag_strategy)
    ch.container_port = manifest.container_port
    ch.visibility = ChallengeVisibility(manifest.visibility)
    ch.hints_json = [h.model_dump() for h in manifest.hints]
    ch.dependencies_json = manifest.dependencies
    ch.metadata_json = manifest.metadata
    ch.enabled = True
    ch.build_status = BuildStatus.pending
    ch.build_log = ""
    ch.uploaded_by = actor.id
    ch.uploaded_at = datetime.utcnow()

    # ── Проверка уникальности container_port ──────────────────────────
    # Порт не должен пересекаться с другими заданиями этого соревнования.
    if ch.container_port is not None:
        clash = (
            db.query(CompetitionChallenge)
            .filter(
                CompetitionChallenge.competition_id == comp.id,
                CompetitionChallenge.id != ch.id,
                CompetitionChallenge.container_port == ch.container_port,
            )
            .first()
        )
        if clash:
            raise HTTPException(
                400,
                f"container_port {ch.container_port} is already used "
                f"by challenge '{clash.slug}' in this competition",
            )

    # ── Проверка зависимостей ─────────────────────────────────────────
    # Все slug'и из manifest.dependencies должны существовать среди заданий
    # этого соревнования. Самозависимость запрещена.
    if manifest.dependencies:
        known_slugs = {
            s for (s,) in (
                db.query(CompetitionChallenge.slug)
                .filter(CompetitionChallenge.competition_id == comp.id)
                .all()
            )
        }
        known_slugs.add(ch.slug)

        unknown = [s for s in manifest.dependencies if s not in known_slugs]
        if unknown:
            raise HTTPException(
                400,
                f"Unknown dependencies: {', '.join(unknown)}. "
                f"Available in this competition: "
                f"{', '.join(sorted(known_slugs)) or '(none)'}",
            )

        if ch.slug in manifest.dependencies:
            raise HTTPException(
                400,
                f"Challenge cannot depend on itself: {ch.slug}",
            )

    # ── Файлы задания ─────────────────────────────────────────────────
    for f in parsed.files:
        rel = f.filename
        is_public = not rel.startswith(".") and rel not in ("manifest.yaml", "Dockerfile")
        db.add(CompetitionChallengeFile(
            challenge_id=ch.id,
            filename=rel,
            size=f.size,
            mime=f.mime,
            sha256=f.sha256,
            stored_path=f.stored_path,
            is_public=is_public,
        ))

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="challenge.upload" if existing is None else "challenge.reupload",
        target_type="competition_challenge", target_id=ch.id,
        payload={"slug": slug, "kind": manifest.kind, "type": manifest.type},
    )
    db.commit()
    db.refresh(ch)

    # Сборка — только для kind=docker.
    if ch.kind == ChallengeKind.docker:
        start_build(db, comp, ch, actor)
    else:
        ch.build_status = BuildStatus.ready
        db.commit()
        db.refresh(ch)

    return ch


# ══════════════════════════════════════════════════════════════════════
# Сборка образа
# ══════════════════════════════════════════════════════════════════════

def _parse_memory(value: str) -> int:
    """'2g' -> 2147483648, '512m' -> 536870912, '1024' -> 1024."""
    v = (value or "").strip().lower()
    if not v:
        return 2 * 1024 ** 3
    mult = 1
    if v.endswith("k"):
        mult = 1024
        v = v[:-1]
    elif v.endswith("m"):
        mult = 1024 ** 2
        v = v[:-1]
    elif v.endswith("g"):
        mult = 1024 ** 3
        v = v[:-1]
    try:
        return int(v) * mult
    except ValueError:
        return 2 * 1024 ** 3


def _run_build(challenge_id: int) -> None:
    """Выполняется в отдельном потоке. Открывает свою сессию БД.

    Сборка идёт через hardening:
    - network_mode='none' (если settings.build_no_network)
    - container_limits: memory + cpuquota
    """
    db = SessionLocal()
    try:
        ch = db.query(CompetitionChallenge).filter_by(id=challenge_id).first()
        if not ch:
            return
        comp = db.query(Competition).filter_by(id=ch.competition_id).first()
        if not comp:
            return

        client = _get_client()

        tag = image_tag(comp.slug, ch.slug)
        context_path = str(challenge_root(comp.slug, ch.slug))

        ch.build_status = BuildStatus.building
        ch.build_log = f"$ docker build -t {tag} {context_path}\n"
        if settings.build_no_network:
            ch.build_log += "[security] network=disabled during build\n"
        ch.build_log += (
            f"[security] mem_limit={settings.build_mem_limit}, "
            f"cpu_quota={settings.build_cpu_quota}\n"
        )
        db.commit()

        log_lines: list[str] = []

        build_kwargs: dict = {
            "path": context_path,
            "tag": tag,
            "rm": True,
            "decode": True,
            "pull": False,
            "nocache": False,
            "forcerm": True,
            "container_limits": {
                "memory": _parse_memory(settings.build_mem_limit),
                "cpuquota": settings.build_cpu_quota,
            },
        }
        if settings.build_no_network:
            # docker-py передаёт network_mode в контейнер сборки.
            build_kwargs["network_mode"] = "none"

        try:
            with _build_lock:
                for chunk in client.api.build(**build_kwargs):
                    if "stream" in chunk:
                        log_lines.append(chunk["stream"])
                    elif "error" in chunk:
                        log_lines.append(f"[ERROR] {chunk['error']}\n")
                        raise DockerException(chunk["error"])

            _built_tags.add(tag)
            ch.build_status = BuildStatus.ready
            ch.build_log = ch.build_log + "".join(log_lines) + "\n[OK] build finished\n"
        except (BuildError, DockerException) as e:
            ch.build_status = BuildStatus.failed
            ch.build_log = ch.build_log + "".join(log_lines) + f"\n[FAIL] {e}\n"
        except Exception as e:
            ch.build_status = BuildStatus.failed
            ch.build_log = (
                ch.build_log + "".join(log_lines)
                + f"\n[FAIL] {e}\n{traceback.format_exc()}\n"
            )

        db.commit()
    finally:
        db.close()


def start_build(
    db: Session, comp: Competition, ch: CompetitionChallenge, actor: User,
) -> None:
    if ch.kind != ChallengeKind.docker:
        ch.build_status = BuildStatus.ready
        db.commit()
        return

    ch.build_status = BuildStatus.pending
    ch.build_log = ""
    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="challenge.build.start",
        target_type="competition_challenge", target_id=ch.id,
    )
    db.commit()

    t = threading.Thread(target=_run_build, args=(ch.id,), daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════════
# Обновление / удаление / промоушен
# ══════════════════════════════════════════════════════════════════════

def update_challenge(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    payload: CompetitionChallengeUpdate,
    actor: User,
) -> CompetitionChallenge:
    data = payload.model_dump(exclude_unset=True)
    new_flag = data.pop("flag", None)

    # Валидация container_port.
    if "container_port" in data and data["container_port"] is not None:
        port = data["container_port"]
        from .competition_manifest import RESERVED_PORTS
        if port in RESERVED_PORTS:
            raise HTTPException(400, f"container_port {port} is reserved")
        if not (1 <= port <= 65535):
            raise HTTPException(400, f"container_port out of range: {port}")

        # Проверка конфликта с другими заданиями этого же соревнования.
        clash = (
            db.query(CompetitionChallenge)
            .filter(
                CompetitionChallenge.competition_id == comp.id,
                CompetitionChallenge.id != ch.id,
                CompetitionChallenge.container_port == port,
            )
            .first()
        )
        if clash:
            raise HTTPException(
                400,
                f"container_port {port} is already used by challenge "
                f"'{clash.slug}' in this competition",
            )

    for field, value in data.items():
        if field == "difficulty" and value is not None:
            value = ChallengeDifficulty(value)
        if field == "visibility" and value is not None:
            value = ChallengeVisibility(value)
        if field == "dynamic_flag_strategy" and value is not None:
            value = DynamicFlagStrategy(value)
        setattr(ch, field, value)

    if new_flag:
        ch.flag_hash = hashlib.sha256(new_flag.strip().encode("utf-8")).hexdigest()

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="challenge.update",
        target_type="competition_challenge", target_id=ch.id,
        payload={"changed": list(data.keys()) + (["flag"] if new_flag else [])},
    )
    db.commit()
    db.refresh(ch)
    return ch


def delete_challenge(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    actor: User,
) -> None:
    # Удаляем папку с диска.
    root = challenge_root(comp.slug, ch.slug)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    # Удаляем образ, если был.
    tag = image_tag(comp.slug, ch.slug)
    try:
        _get_client().images.remove(tag, force=True)
    except NotFound:
        pass
    except DockerException:
        pass
    _built_tags.discard(tag)

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="challenge.delete",
        target_type="competition_challenge", target_id=ch.id,
        payload={"slug": ch.slug},
    )
    db.delete(ch)
    db.commit()


def promote_to_global(
    db: Session,
    comp: Competition,
    ch: CompetitionChallenge,
    actor: User,
    *,
    new_slug: Optional[str],
    points: Optional[int],
    enabled: bool,
) -> GlobalChallenge:
    """Создаёт глобальный Challenge на основе задания соревнования."""
    if actor.role != UserRole.admin:
        raise HTTPException(403, "Admin only")

    if ch.kind != ChallengeKind.docker:
        raise HTTPException(400, "Only kind=docker challenges can be promoted to global")

    if ch.build_status != BuildStatus.ready:
        raise HTTPException(409, "Challenge image is not built")

    if not ch.container_port:
        raise HTTPException(409, "container_port is required")

    base_slug = new_slug or ch.slug
    final_slug = base_slug
    suffix = 1
    while db.query(GlobalChallenge).filter_by(slug=final_slug).first():
        suffix += 1
        final_slug = f"{base_slug}-{suffix}"

    # Копируем папку в глобальный challenges_dir (плоско).
    src = challenge_root(comp.slug, ch.slug)
    dst = Path(settings.challenges_dir) / final_slug
    if dst.exists():
        raise HTTPException(409, f"Directory {dst} already exists")
    shutil.copytree(src, dst)

    # Собираем образ под глобальным тегом.
    global_tag = f"ctf-challenge-{final_slug}:latest"
    try:
        with _build_lock:
            _get_client().images.build(path=str(dst), tag=global_tag, rm=True)
    except Exception as e:
        shutil.rmtree(dst, ignore_errors=True)
        raise HTTPException(500, f"Failed to build global image: {e}")

    challenge = GlobalChallenge(
        slug=final_slug,
        title=ch.title,
        category=ch.category,
        difficulty=(
            ch.difficulty.value
            if hasattr(ch.difficulty, "value")
            else str(ch.difficulty)
        ),
        points=points or ch.points,
        description=ch.description_md[:4000],
        flag_hash=ch.flag_hash,
        container_port=ch.container_port,
        enabled=enabled,
    )
    db.add(challenge)
    db.flush()

    ch.source_global_challenge_id = challenge.id

    competition_audit.log_action(
        db, competition_id=comp.id, actor=actor,
        action="challenge.promote",
        target_type="competition_challenge", target_id=ch.id,
        payload={"global_slug": final_slug, "global_id": challenge.id},
    )
    db.commit()
    db.refresh(challenge)
    return challenge