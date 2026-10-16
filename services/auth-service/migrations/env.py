"""
Alembic environment для async SQLAlchemy.

Конфигурация:
- URL БД берётся из app.config.Settings.database_url
- Метаданные — из app.database.Base
- Все модели импортируются, чтобы Alembic их видел
- Async engine (postgresql+asyncpg)

Запуск:
    uv run alembic revision --autogenerate -m "message"   # создать миграцию
    uv run alembic upgrade head                            # применить
    uv run alembic downgrade -1                            # откатить одну
    uv run alembic current                                 # текущая ревизия
    uv run alembic history --verbose                       # история
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Импорт наших моделей ───────────────────────────────────────────────────
# ВАЖНО: импортируем Base и все модели, чтобы Alembic их увидел
# в Base.metadata. Без этого autogenerate создаст пустые миграции.
from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401 — регистрирует модели в Base.metadata


# ── Alembic Config ─────────────────────────────────────────────────────────
config = context.config

# Логирование из alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ═══════════════════════════════════════════════════════════════════════════
# Экранирование % в URL
# ═══════════════════════════════════════════════════════════════════════════
#
# Alembic хранит значения через configparser, а он трактует `%` как
# начало интерполяции `%(name)s`. Если DSN содержит `%` (например, пароль
# URL-энкоднут или кто-то поставил `%` в пароле вручную), configparser
# падает с:
#
#     ValueError: invalid interpolation syntax in '...' at position N
#
# Стандартное решение — заменить `%` на `%%` перед передачей в
# set_main_option. configparser расценит это как escape-последовательность
# и вернёт оригинальный `%` при чтении.
#
# Примеры URL, которые без экранирования сломали бы Alembic:
#   postgresql+asyncpg://user:p%40ss@host/db       (пароль p@ss)
#   postgresql+asyncpg://user:p%D0%B0%D1%81@host   (URL-энкод кириллицы)
#
# С `%%` эти URL работают корректно.
#
def _escape_percent(value: str) -> str:
    """
    Экранировать `%` для configparser.

    Единственный символ, который configparser воспринимает как
    специальный по умолчанию, — это `%`. Заменяем `%` на `%%`.
    """
    return value.replace("%", "%%")


_database_url_raw = get_settings().database_url
config.set_main_option("sqlalchemy.url", _escape_percent(_database_url_raw))

# Метаданные для autogenerate
target_metadata = Base.metadata


# ── Offline migrations ─────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """
    Offline-режим: генерация SQL без подключения к БД.

    Используется для:
    - Ревью SQL перед применением
    - Применения через DBA (у которого нет доступа к коду)
    - CI: alembic upgrade head --sql > migration.sql
    """
    # URL уже сохранён в config через _escape_percent выше. При чтении
    # configparser вернёт оригинальный `%` (однократное раскрытие `%%`).
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,             # отслеживать изменения типов
        compare_server_default=True,   # отслеживать изменения default
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations ──────────────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    """Синхронный callback для запуска миграций внутри async engine."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        # Важно для PostgreSQL: не игнорировать enum'ы
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async-режим: миграции через asyncpg."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # для миграций пул не нужен
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Точка входа для online-миграций."""
    asyncio.run(run_async_migrations())


# ── Точка входа ────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()