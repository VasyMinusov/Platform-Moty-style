# Миграция на версию с соревнованиями

Инструкция для существующего деплоя. Все операции идемпотентны, откат —
через `alembic downgrade` (не рекомендуется, есть потеря данных).

## Требования

- Docker + Docker Compose.
- Backend пересобирается.
- Есть доступ к volume `db_data`.

## Шаги

### 1. Резервная копия БД

```bash
docker compose exec db pg_dump -U ctf -d ctf > backup_$(date +%Y%m%d_%H%M%S).sql
```

Убедитесь, что файл не пустой.

### 2. Забрать новую версию

```bash
git fetch
git checkout feature/competitions
```

### 3. Проверить `docker-compose.yml`

Убедитесь, что volume `./challenges:/challenges` **без** `:ro`:

```yaml
backend:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - ./challenges:/challenges
```

Backend должен писать в `/challenges/competitions`.

### 4. Пересобрать backend

```bash
docker compose down
docker compose build backend
docker compose up
```

### 5. Alembic применит миграции автоматически

При старте backend:

1. `_bootstrap_legacy_db` — если в БД уже есть `users`, но нет
   `alembic_version`, стампит `0001_legacy`.
2. `upgrade head` — накатывает `0002_competitions`, `0003_notifications`.

В логах:

```
[INIT] Обнаружена legacy-БД: застамплена как 0001_legacy
INFO: Running upgrade 0001_legacy -> 0002_competitions, competitions initial
INFO: Running upgrade 0002_competitions -> 0003_notifications, notifications
INFO: Application startup complete.
```

### 6. Проверить состояние

```bash
# Версия миграции
docker compose exec db psql -U ctf -d ctf -c "SELECT * FROM alembic_version;"

# Список таблиц
docker compose exec db psql -U ctf -d ctf -c "\dt"
```

Ожидаем увидеть все `competition_*`, `notifications` и `alembic_version`.

### 7. Проверить старый функционал

- `/api/challenges` работает.
- Запуск глобального инстанса работает.
- Задания синхронизируются (`/admin/challenges/sync`).

### 8. Создать первое соревнование

Через UI: `/admin/competitions/new`.

Или через API (см. `docs/COMPETITIONS.md`).

## Откат

Если что-то пошло не так:

```bash
docker compose down
docker compose exec db psql -U ctf -d ctf < backup_YYYYMMDD_HHMMSS.sql
git checkout <предыдущий тег>
docker compose build backend
docker compose up
```

Откат через `alembic downgrade` технически возможен, но удаляет все
данные соревнований.

## Известные особенности

- На существующей БД `challenge_instances.user_id, challenge_id`
  уникальность заменяется на три partial unique index'а. Существующие
  строки не задеваются (competition_id = NULL).
- Volume `./challenges` должен быть доступен на запись. Если он
  смонтирован read-only, загрузка ZIP не сработает.
- Rate limiting включается автоматически. Если в тестах мешает —
  выставьте `RATE_LIMIT_ENABLED=false` в `.env`.
- Allowlist базовых образов. Если хотите отключить —
  `BUILD_ENFORCE_BASE_IMAGE_ALLOWLIST=false`.