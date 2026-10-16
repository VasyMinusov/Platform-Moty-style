"""
Централизованная конфигурация структурированного логирования.

Этот модуль настраивает structlog с единым processor pipeline и
маршрутизирует ВСЕ логи (stdlib, uvicorn, sqlalchemy, fastapi) через
structlog.ProcessorFormatter.

- dev/local: цветной человекочитаемый вывод (ConsoleRenderer)
- prod/stage: машиночитаемый JSON (JSONRenderer + orjson)

Ключевая особенность: correlation_id автоматически добавляется
в каждый лог через contextvars, что позволяет сквозную трассировку.
"""

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any, cast
from uuid import uuid4

import structlog
from structlog.types import Processor

from app.config import get_settings

# ─── Correlation ID: async-safe context variable ────────────────────────────
#
# contextvars — это async-safe замена thread-local. Каждая корутина
# (запрос FastAPI) получает собственный контекст, поэтому request_id
# из одного запроса не "протечёт" в другой, даже при конкурентной обработке.
#
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Получить correlation_id текущего запроса (или None, если вне запроса)."""
    return correlation_id_var.get()


def set_correlation_id(cid: str) -> None:
    """Установить correlation_id для текущего контекста."""
    correlation_id_var.set(cid)


def generate_correlation_id() -> str:
    """Сгенерировать короткий (8 символов) correlation ID."""
    return str(uuid4())[:8]


# ─── Processor: добавляет correlation_id в каждый лог-эвент ─────────────────


def add_correlation_id(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """
    Structlog processor: добавляет correlation_id в event_dict.

    Structlog processors — это функции, которые получают event_dict и
    возвращают его модифицированную версию. Порядок в pipeline критичен:
    этот processor должен идти до финального рендерера (JSON/Console).
    """
    cid = correlation_id_var.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


# ─── Shared processors (общие для dev и prod) ───────────────────────────────


def _shared_processors() -> list[Processor]:
    """
    Processors, выполняемые для всех логов перед финальным рендерингом.

    Порядок важен:
    1. merge_contextvars — подхватывает bind_contextvars() данные
    2. add_log_level — добавляет "level": "info" и т.д.
    3. add_correlation_id — добавляет correlation_id из contextvars
    4. TimeStamper — добавляет "timestamp" в ISO формате
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_correlation_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


# ─── Публичная функция конфигурации ────────────────────────────────────────


def configure_logging() -> None:
    """
    Настроить логирование. Вызывается ОДИН РАЗ при старте приложения
    (в lifespan FastAPI или в main перед uvicorn.run).

    После вызова:
    - Все structlog-логи идут через единый pipeline
    - stdlib-логи (uvicorn, sqlalchemy, fastapi) перенаправлены через
      ProcessorFormatter в тот же формат
    - correlation_id автоматически попадает в каждый лог
    """
    settings = get_settings()
    is_dev = settings.app_env in ("local", "dev")
    log_level = getattr(logging, settings.log_level.upper())

    # Финальный рендерер: Console для dev, JSON для prod
    if is_dev:
        # ConsoleRenderer с цветами и читаемым форматом
        final_renderer: Processor = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )
    else:
        # JSONRenderer + orjson (быстрее стандартного json)
        # orjson опционален — fallback на стандартный json
        try:
            import orjson

            final_renderer = structlog.processors.JSONRenderer(serializer=orjson.dumps)
        except ImportError:
            final_renderer = structlog.processors.JSONRenderer()

    # ── Конфигурация structlog ────────────────────────────────────────────
    structlog.configure(
        processors=[
            *_shared_processors(),
            # ProcessorFormatter.wrap_for_formatter — мост между structlog
            # и stdlib logging. Позволяет stdlib-логгерам (uvicorn и т.д.)
            # использовать те же processors и рендерер.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        # Фильтрация по уровню до попадания в processors
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ── Мост для stdlib logging (uvicorn, sqlalchemy) ─────────────────────
    #
    # ProcessorFormatter перехватывает stdlib-логи, прогоняет их через
    # наши processors и рендерит тем же рендерером, что и structlog.
    # Результат: единый формат логов для всего приложения.
    #
    formatter = structlog.stdlib.ProcessorFormatter(
        # Processors, применяемые ТОЛЬКО к stdlib-логам (не structlog).
        # remove_processors_meta убирает служебные ключи, которые
        # ProcessorFormatter добавляет для совместимости.
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_renderer,
        ],
    )

    # ── Настройка root logger ─────────────────────────────────────────────
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # убрать дефолтные handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # ── Приглушить шумные логгеры ─────────────────────────────────────────
    #
    # uvicorn.access — стандартный access-log uvicorn.
    # Отключаем, потому что сами будем логировать access через middleware
    # (структурированно, с correlation_id).
    #
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False

    # SQLAlchemy в prod логирует все SQL-запросы на уровне INFO — слишком шумно.
    # Устанавливаем WARNING, чтобы видеть только проблемы.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.WARNING if settings.is_production else logging.INFO
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Получить structlog-логгер.

    Использование:
        log = get_logger(__name__)
        log.info("user_created", user_id=42)
        # → {"event": "user_created", "user_id": 42, "level": "info",
        #    "correlation_id": "a1b2c3d4", "timestamp": "..."}
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
