"""Проверки безопасности Dockerfile задания соревнования.

Не заменяет собой полноценную песочницу, но отсекает самые частые
опасные паттерны, которые могут навредить хост-системе.
"""
import re
from pathlib import Path

from fastapi import HTTPException


# Базовые образы, которые разрешены. Проверка отключается флагом
# settings.build_enforce_base_image_allowlist = False.
DEFAULT_BASE_IMAGE_ALLOWLIST = {
    "python:3.12-slim",
    "python:3.11-slim",
    "python:3.12-alpine",
    "python:3.11-alpine",
    "node:20-alpine",
    "node:22-alpine",
    "nginx:alpine",
    "alpine:3.19",
    "alpine:3.20",
    "ubuntu:22.04",
    "ubuntu:24.04",
    "debian:bookworm-slim",
    "debian:bullseye-slim",
    "openjdk:17-slim",
    "openjdk:21-slim",
    "golang:1.22-alpine",
    "golang:1.23-alpine",
    "rust:1.75-slim",
    "tomcat:9.0-jdk11-temurin",
    "tomcat:10.1-jdk17-temurin",
}


# Опасные паттерны в Dockerfile.
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*ADD\s+https?://", re.M | re.I),
     "ADD from URL is not allowed; use a proxy or bundle files"),
    (re.compile(r"--privileged", re.I),
     "Dockerfile must not require --privileged"),
    (re.compile(r"--network\s*=\s*host", re.I),
     "Dockerfile must not use host network"),
    (re.compile(r"--pid\s*=\s*host", re.I),
     "Dockerfile must not use host PID namespace"),
    (re.compile(r"--ipc\s*=\s*host", re.I),
     "Dockerfile must not use host IPC namespace"),
    (re.compile(r"--uts\s*=\s*host", re.I),
     "Dockerfile must not use host UTS namespace"),
    (re.compile(r"^\s*COPY\s+--from=[^\s]+", re.M | re.I),
     "Multi-stage COPY --from is not allowed"),
    (re.compile(r"^\s*VOLUME\s+/", re.M | re.I),
     "VOLUME is not allowed"),
    (re.compile(r"^\s*RUN\s+.*mount\s*=\s*type=bind", re.M | re.I),
     "Bind mounts are not allowed"),
    (re.compile(r"^\s*RUN\s+.*/var/run/docker\.sock", re.M | re.I),
     "Access to host Docker socket is not allowed"),
]


def _extract_base_images(dockerfile_text: str) -> list[str]:
    images = []
    for line in dockerfile_text.splitlines():
        m = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)", line, re.I)
        if m:
            images.append(m.group(1).strip())
    return images


def _check_base_image_allowlist(images: list[str]) -> None:
    from ..config import settings
    if not getattr(settings, "build_enforce_base_image_allowlist", True):
        return
    allowed = DEFAULT_BASE_IMAGE_ALLOWLIST
    for img in images:
        # "python:3.12-slim" — точное совпадение.
        # Разрешаем префикс с тегом, но не digest/registry.
        if img in allowed:
            continue
        # Разрешаем образы из allowlist без явного тега: "python" -> "python:latest".
        base = img.split(":", 1)[0]
        if any(a.split(":", 1)[0] == base for a in allowed):
            continue
        raise HTTPException(
            400,
            f"Base image '{img}' is not in allowlist. "
            f"Allowed base images: {', '.join(sorted(allowed))}",
        )


def validate_dockerfile(dockerfile_path: Path) -> None:
    """Проверяет Dockerfile на опасные инструкции. Бросает HTTPException."""
    if not dockerfile_path.exists():
        raise HTTPException(400, "Dockerfile not found")

    text = dockerfile_path.read_text(encoding="utf-8", errors="replace")

    # 1. Запрещённые паттерны.
    for pattern, reason in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise HTTPException(400, f"Dockerfile validation failed: {reason}")

    # 2. Базовая проверка на слишком большое число RUN.
    if text.count("\nRUN ") + text.count("\nRUN\t") > 60:
        raise HTTPException(400, "Dockerfile has too many RUN instructions")

    # 3. Allowlist базовых образов.
    images = _extract_base_images(text)
    if not images:
        raise HTTPException(400, "Dockerfile has no FROM instruction")
    _check_base_image_allowlist(images)