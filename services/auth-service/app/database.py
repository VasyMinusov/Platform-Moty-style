"""
Асинхронный слой доступа к БД.

Стек:
- SQLAlchemy 2.0 (async API)
- asyncpg (драйвер PostgreSQL)
- async_sessionmaker (фабрика сессий)

Паттерн: сессия создаётся на один запрос, коммитится автоматически
при успехе, откатывается при исключении. Это избавляет роутеры от
ручного управления транзакциями.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ─── Declarative Base ───────────────────────────────────────────────────────
#
# SQLAlchemy 2.0 использует DeclarativeBase как базовый класс для всех
# моделей. Наследуемся от него в models.py:
#
#   class User(Base):
#       __tablename__ = "users"
#       ...
#
# В отличие от старого declarative_base(), это типизированный класс,
# который корректно работает с mypy и IDE-автодополнением.
#
class Base(DeclarativeBase):
    """
    Базовый класс для всех ORM-моделей.

    Можно расширить общими миксинами (id, created_at, updated_at),
    но для auth-сервиса мы определим их явно в каждой модели —
    так гибче при эволюции схемы.
    """

    def to_dict(self) -> dict[str, Any]:
        """Утилита для сериализации модели (полезно в логах/отладке)."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


# ─── Engine: singleton на весь процесс ──────────────────────────────────────
#
# Engine создаётся ОДИН раз и переиспользуется. Внутри держит пул
# соединений — критично для производительности: открытие нового
# TCP-соединения к Postgres на каждый запрос убивает latency.
#
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Получить (или лениво создать) async engine."""
    global _engine

    if _engine is None:
        settings = get_settings()

        engine_kwargs: dict[str, Any] = {
            "echo": settings.db_echo,
            "pool_pre_ping": True,
            "future": True,
        }

        if settings.is_development and settings.app_debug:
            # В dev с hot-reload лучше NullPool
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = settings.db_pool_size
            engine_kwargs["max_overflow"] = settings.db_max_overflow
            engine_kwargs["pool_recycle"] = settings.db_pool_recycle

        _engine = create_async_engine(
            settings.database_url,
            **engine_kwargs,
        )

        log.info(
            "db_engine_created",
            host=settings.postgres_host,
            port=settings.postgres_port,
            database=settings.postgres_db,
            pool="NullPool" if "poolclass" in engine_kwargs else "QueuePool",
        )

    return _engine


# ─── Session factory ────────────────────────────────────────────────────────
#
# async_sessionmaker — фабрика сессий. Один вызов () → новая сессия.
# Параметры:
#   expire_on_commit=False — после commit объекты остаются доступными.
#       Без этого SQLAlchemy "протухает" атрибуты, и обращение к ним
#       после коммита триггерит ленивую загрузку (в async это ошибка).
#   autoflush=False — не делать flush перед каждым запросом. Явный
#       контроль: flush() вызываем сами, когда нужно получить id и т.п.
#
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Ленивая инициализация фабрики сессий."""
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    return _session_factory


# ─── FastAPI dependency: get_db ─────────────────────────────────────────────
#
# Это главная точка входа для роутеров. Использование:
#
#   @router.get("/me")
#   async def me(db: AsyncSession = Depends(get_db)):
#       ...
#
# Паттерн "сессия на запрос" с автокоммитом:
#   - при успехе: commit()
#   - при исключении: rollback() и проброс наверх
#   - в конце: close() возвращает соединение в пул
#
async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI-зависимость: выдаёт AsyncSession на время запроса.

    Транзакционная семантика:
      - Роутер делает изменения через ORM.
      - При выходе из зависимости БЕЗ исключения — commit.
      - При исключении — rollback и re-raise.

    Это освобождает роутеры от boilerplate:
        async with session.begin():
            ...
    Вместо этого просто пишем код, а коммит происходит автоматически.
    """
    factory = get_session_factory()

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            # Логируем с exc_info=True — ProcessorFormatter.format_exc_info
            # превратит это в структурированный traceback в JSON.
            log.exception(
                "db_session_rollback",
                exc_info=True,
            )
            raise
        finally:
            await session.close()


# ─── Управление жизненным циклом ────────────────────────────────────────────
#
# Вызывается из lifespan FastAPI (см. main.py). При shutdown
# корректно закрываем пул соединений — иначе процесс висит,
# пока Postgres не разорвёт соединения по таймауту.
#
async def dispose_engine() -> None:
    """Закрыть пул соединений. Вызывать при shutdown приложения."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        log.info("db_engine_disposed")

    _engine = None
    _session_factory = None


# ─── Health-check БД ────────────────────────────────────────────────────────
#
# Отдельная функция для /health эндпоинта: проверяет, что БД доступна.
# Использует text("SELECT 1") — минимальная нагрузка.
#
async def check_db_connection() -> bool:
    """Проверить, что БД доступна. Возвращает True/False."""
    from sqlalchemy import text

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.error("db_healthcheck_failed", error=str(exc))
        return False
