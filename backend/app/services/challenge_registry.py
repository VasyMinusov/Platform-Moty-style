"""
Реестр заданий (модулей).

ГЛАВНАЯ ИДЕЯ МАСШТАБИРОВАНИЯ:
Чтобы добавить новое задание, НЕ нужно трогать код платформы.
Достаточно создать папку в CHALLENGES_DIR со структурой:

    challenges/
      my-new-challenge/
        manifest.yaml   <- метаданные (см. пример ниже)
        Dockerfile      <- как собрать уязвимое приложение

и вызвать sync_challenges(db) (это происходит автоматически при старте
приложения и по кнопке "Sync" в админке). Функция сама найдёт папку,
прочитает manifest.yaml и создаст/обновит запись в БД.

Если нужен явный контроль "какие модули включены" — заполните
ENABLED_CHALLENGES ниже. Пустой список = включены все найденные папки.
Непустой список = добавление модуля становится ровно одной строкой в
этом списке.

Пример manifest.yaml:
---
title: "SQL Injection 101"
category: "web"
difficulty: "easy"
points: 100
description: "Найди способ обойти форму логина через SQL-инъекцию."
flag: "flag{sql_1nj3ct10n_1s_2asy}"
container_port: 80
"""
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Challenge

ENABLED_CHALLENGES: list[str] = []  # пусто = автоподключение всех папок


@dataclass
class ManifestData:
    slug: str
    title: str
    category: str
    difficulty: str
    points: int
    description: str
    flag_hash: str
    container_port: int


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def discover_manifests() -> list[ManifestData]:
    base = Path(settings.challenges_dir)
    if not base.exists():
        return []

    found: list[ManifestData] = []
    for entry in sorted(base.iterdir()):
        manifest_path = entry / "manifest.yaml"
        if not entry.is_dir() or not manifest_path.exists():
            continue

        slug = entry.name
        if ENABLED_CHALLENGES and slug not in ENABLED_CHALLENGES:
            continue

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        flag = data.get("flag")
        flag_hash = data.get("flag_hash") or (_sha256(flag) if flag else None)
        if not flag_hash:
            continue

        found.append(ManifestData(
            slug=slug,
            title=data.get("title", slug),
            category=data.get("category", "misc"),
            difficulty=data.get("difficulty", "easy"),
            points=int(data.get("points", 100)),
            description=data.get("description", ""),
            flag_hash=flag_hash,
            container_port=int(data.get("container_port", 80)),
        ))
    return found


def sync_challenges(db: Session) -> int:
    """Синхронизирует таблицу challenges с манифестами на диске.
    Вызывается при старте приложения и/или через админ-эндпоинт /admin/challenges/sync."""
    manifests = discover_manifests()
    for m in manifests:
        challenge = db.query(Challenge).filter(Challenge.slug == m.slug).first()
        if challenge is None:
            challenge = Challenge(slug=m.slug)
            db.add(challenge)

        challenge.title = m.title
        challenge.category = m.category
        challenge.difficulty = m.difficulty
        challenge.points = m.points
        challenge.description = m.description
        challenge.flag_hash = m.flag_hash
        challenge.container_port = m.container_port
        challenge.enabled = True

    known_slugs = {m.slug for m in manifests}
    for challenge in db.query(Challenge).all():
        if challenge.slug not in known_slugs:
            challenge.enabled = False

    db.commit()
    return len(manifests)


def image_tag_for(slug: str) -> str:
    return f"ctf-challenge-{slug}:latest"


def build_context_for(slug: str) -> str:
    return os.path.join(settings.challenges_dir, slug)
