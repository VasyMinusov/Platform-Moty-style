"""Парсинг и валидация ZIP-архива задания соревнования."""
import hashlib
import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import HTTPException

from ..config import settings
from ..schemas_competitions import Manifest


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_MANIFEST = "manifest.yaml"

# Запрещённые имена и префиксы внутри ZIP.
FORBIDDEN_NAMES = {".DS_Store", "Thumbs.db", "__MACOSX"}
FORBIDDEN_PREFIXES = (".__MACOSX/", "__MACOSX/")

# Порта, которые платформа использует под себя. container_port не может
# совпадать ни с одним из них.
RESERVED_PORTS = {80, 443, 5173, 5432, 8000}


@dataclass
class ParsedFile:
    filename: str
    size: int
    sha256: str
    stored_path: str
    mime: str | None = None


@dataclass
class ParsedChallenge:
    manifest: Manifest
    slug: str
    root_dir: Path
    files: list[ParsedFile] = field(default_factory=list)
    total_size: int = 0


def _safe_extract_path(root: Path, member: str) -> Path:
    target = (root / member).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved) + os.sep) and target != root_resolved:
        raise HTTPException(400, f"Unsafe path in ZIP: {member}")
    return target


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_container_port(manifest: Manifest) -> None:
    if manifest.kind != "docker":
        return
    if not manifest.container_port:
        raise HTTPException(400, "container_port is required for kind=docker")
    if manifest.container_port in RESERVED_PORTS:
        raise HTTPException(
            400,
            f"container_port {manifest.container_port} is reserved by platform",
        )
    if not (1 <= manifest.container_port <= 65535):
        raise HTTPException(400, f"container_port out of range: {manifest.container_port}")


def parse_zip(zip_bytes: bytes, dest_dir: Path, *, expected_slug: str | None = None) -> ParsedChallenge:
    max_bytes = settings.competition_zip_max_bytes
    max_files = settings.competition_zip_max_files

    if len(zip_bytes) > max_bytes:
        raise HTTPException(413, f"ZIP too large: {len(zip_bytes)} bytes")

    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise HTTPException(400, f"Invalid ZIP: {e}")

    names = zf.namelist()
    if len(names) > max_files:
        raise HTTPException(413, f"Too many files in ZIP: {len(names)}")

    # 1. Валидация и безопасная распаковка.
    seen = set()
    for name in names:
        if name in seen:
            raise HTTPException(400, f"Duplicate entry in ZIP: {name}")
        seen.add(name)

        base = Path(name).name
        if base in FORBIDDEN_NAMES:
            raise HTTPException(400, f"Forbidden file in ZIP: {name}")
        if any(name.startswith(p) for p in FORBIDDEN_PREFIXES):
            raise HTTPException(400, f"Forbidden path in ZIP: {name}")

        if name.startswith("/") or ".." in Path(name).parts:
            raise HTTPException(400, f"Unsafe path in ZIP: {name}")

        info = zf.getinfo(name)
        # Запрет symlink.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise HTTPException(400, f"Symlinks are not allowed: {name}")

        target = _safe_extract_path(dest_dir, name)
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            dst.write(src.read())

    # 2. Манифест.
    manifest_path = dest_dir / ALLOWED_MANIFEST
    if not manifest_path.exists():
        raise HTTPException(400, "manifest.yaml not found in ZIP root")

    with open(manifest_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        manifest = Manifest.model_validate(raw)
    except Exception as e:
        raise HTTPException(400, f"Invalid manifest: {e}")

    # 3. Slug.
    if expected_slug:
        slug = expected_slug
    else:
        slug = raw.get("slug") or dest_dir.name
    if not SLUG_RE.match(slug):
        raise HTTPException(400, f"Invalid slug: {slug}")
    if len(slug) > 64:
        raise HTTPException(400, "slug is too long")

    # 4. Структура по kind.
    if manifest.kind == "docker":
        dockerfile_path = (
            manifest.metadata.get("docker", {}).get("dockerfile_path", "Dockerfile")
            if isinstance(manifest.metadata, dict)
            else "Dockerfile"
        )
        if not (dest_dir / dockerfile_path).exists() and not (dest_dir / "Dockerfile").exists():
            raise HTTPException(400, "Dockerfile not found for kind=docker")
    elif manifest.kind == "static":
        public_dir = dest_dir / "public"
        if not public_dir.exists() or not any(public_dir.iterdir()):
            raise HTTPException(400, "public/ directory is empty for kind=static")

    # 5. metadata.
    try:
        manifest.validate_metadata()
    except Exception as e:
        raise HTTPException(400, f"Invalid metadata for type={manifest.type}: {e}")

    # 6. Порт.
    _validate_container_port(manifest)

    # 7. Сбор файлов.
    files: list[ParsedFile] = []
    total = 0
    for p in dest_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(dest_dir).as_posix()
            size = p.stat().st_size
            total += size
            files.append(ParsedFile(
                filename=rel,
                size=size,
                sha256=_sha256_file(p),
                stored_path=str(p),
            ))

    return ParsedChallenge(
        manifest=manifest,
        slug=slug,
        root_dir=dest_dir,
        files=files,
        total_size=total,
    )