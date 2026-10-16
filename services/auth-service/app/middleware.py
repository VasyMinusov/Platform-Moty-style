"""
Middleware для сквозной трассировки и access logging.

Архитектурное решение: используем чистый ASGI middleware вместо
BaseHTTPMiddleware.

Причина: BaseHTTPMiddleware создаёт 7 промежуточных объектов на
каждый запрос [citation:2], ломает streaming responses и заставляет
background tasks выполняться в foreground [citation:19].

ASGI middleware работает на уровне scope/receive/send и не имеет
этих проблем.
"""

import asyncio
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_config import (
    correlation_id_var,
    generate_correlation_id,
    get_logger,
)
from app.metrics import http_requests_inprogress

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Пути, которые не логируются
# ═══════════════════════════════════════════════════════════════════════════

SKIP_PATHS = frozenset(
    {
        "/health",
        "/healthz",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    }
)


# ═══════════════════════════════════════════════════════════════════════════
# Correlation ID + Access Log Middleware (ASGI)
# ═══════════════════════════════════════════════════════════════════════════


class CorrelationLoggingMiddleware:
    """
    ASGI middleware: correlation ID + access log.

    На каждый HTTP-запрос:
    1. Извлекает X-Correlation-ID из headers или генерирует новый.
    2. Устанавливает correlation_id в contextvar (для structlog).
    3. Логирует request_completed / request_failed с timing.
    4. Добавляет X-Correlation-ID в response headers.

    Использование:
        app.add_middleware(CorrelationLoggingMiddleware)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Пропускаем non-HTTP (websocket, lifespan)
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ── 1. Correlation ID ─────────────────────────────────────────────
        headers = dict(scope.get("headers", []))
        incoming_cid = headers.get(b"x-correlation-id", b"").decode() or None

        cid = incoming_cid or generate_correlation_id()
        correlation_id_var.set(cid)
        scope["state"] = scope.get("state", {})
        scope["state"]["correlation_id"] = cid

        # ── 2. Skip paths (health, metrics) ───────────────────────────────
        path = scope.get("path", "")
        skip_logging = path in SKIP_PATHS

        # ── 3. Timing ─────────────────────────────────────────────────────
        start_time = time.perf_counter()

        # ── 4. Обёртка send для перехвата response ────────────────────────
        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

                headers_list = list(message.get("headers", []))
                headers_list.append((b"x-correlation-id", cid.encode()))
                message["headers"] = headers_list

            await send(message)

        # ── 5. Вызов приложения ───────────────────────────────────────────
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            if not skip_logging:
                log.error(
                    "request_failed",
                    method=scope.get("method"),
                    path=path,
                    duration_ms=round(duration_ms, 2),
                    error=str(exc),
                    exc_info=True,
                )
            raise

        # ── 6. Access log ─────────────────────────────────────────────────
        duration_ms = (time.perf_counter() - start_time) * 1000

        if not skip_logging:
            if status_code and status_code >= 500:
                log_fn = log.error
            elif status_code and status_code >= 400:
                log_fn = log.warning
            else:
                log_fn = log.info

            client = scope.get("client")
            client_ip = client[0] if client else None

            log_fn(
                "request_completed",
                method=scope.get("method"),
                path=path,
                query=scope.get("query_string", b"").decode() or None,
                status=status_code,
                duration_ms=round(duration_ms, 2),
                client_ip=client_ip,
                user_agent=headers.get(b"user-agent", b"").decode() or None,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Active Requests Middleware
# ═══════════════════════════════════════════════════════════════════════════


# Module-level ссылка на единственный инстанс middleware.
#
# FastAPI создаёт middleware в create_app() через add_middleware(Class),
# а не через add_middleware(instance). Это значит, что мы не можем
# передать готовый объект в lifespan напрямую. Решение — сохранить
# ссылку на инстанс в module-level переменной внутри __init__.
#
# В тестах create_app() может вызываться многократно — каждый раз
# _active_requests_instance перезаписывается последним инстансом.
# Это нормально: в тестах мы не проверяем shutdown lifespan'а через
# реальный ASGITransport (он не триггерит startup/shutdown).
_active_requests_instance: ActiveRequestsMiddleware | None = None


class ActiveRequestsMiddleware:
    """
    ASGI middleware: учёт активных HTTP-запросов.

    Две задачи:

    1. **Метрика** `http_requests_inprogress` — Gauge, обновляется на
       входе/выходе. Заменяет встроенный в prometheus-fastapi-instrumentator
       (should_instrument_requests_inprogress=True), который создаётся
       в InstrumentatorMiddleware.__init__ → DuplicateTimeseries при
       многократном create_app() (тесты).

    2. **Graceful shutdown** — внутренний счётчик `_active`. При
       SIGTERM lifespan вызывает `wait_for_zero(timeout)`, чтобы дать
       текущим запросам завершиться до закрытия пулов БД/Redis.

    Инкремент счётчика происходит ДО вызова app, декремент — в `finally`,
    чтобы при исключении в обработчике счётчик всё равно обнулился.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

        # Счётчик активных запросов. Модифицируется под _lock.
        # Не используем атомарный int (в asyncio всё равно один поток,
        # но инкремент/проверка в wait_for_zero — критическая секция).
        self._active: int = 0
        self._lock = asyncio.Lock()

        # Сохраняем ссылку в module-level для lifespan.
        global _active_requests_instance
        _active_requests_instance = self

    @property
    def active_count(self) -> int:
        """
        Текущее число активных запросов.

        Не под lock: чтение int атомарно в CPython. Используется для
        логирования при таймауте — точность не критична.
        """
        return self._active

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Пропускаем non-HTTP (websocket, lifespan) — они не считаются
        # «запросами» для graceful shutdown.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async with self._lock:
            self._active += 1

        http_requests_inprogress.inc()
        try:
            await self.app(scope, receive, send)
        finally:
            http_requests_inprogress.dec()
            async with self._lock:
                self._active -= 1

    async def wait_for_zero(self, timeout: float) -> bool:
        """
        Дождаться, пока все активные запросы завершатся.

        Возвращает:
        - True  — счётчик дошёл до нуля в пределах timeout.
        - False — таймаут истёк, запросы всё ещё активны.

        Цикл с asyncio.sleep(0.1) — компромисс между отзывчивостью и
        нагрузкой на event loop. Более точный вариант — Condition /
        Event, но для shutdown-сценария (редкое событие) поллинг проще
        и не создаёт лишних объектов на каждый запрос.

        ВАЖНО: вызывать ТОЛЬКО из lifespan на shutdown, когда новые
        запросы уже не принимаются (uvicorn с --timeout-graceful-shutdown
        перестаёт принимать соединения при SIGTERM до вызова shutdown
        у приложения).
        """
        # get_running_loop() — мы внутри async-функции, loop точно есть.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while True:
            async with self._lock:
                if self._active == 0:
                    return True

            if loop.time() >= deadline:
                return False

            await asyncio.sleep(0.1)


def get_active_requests_middleware() -> ActiveRequestsMiddleware:
    """
    Получить инстанс ActiveRequestsMiddleware, созданный в create_app().

    Нужно для lifespan: FastAPI не отдаёт middleware-инстансы наружу,
    а нам нужно вызвать wait_for_zero() на shutdown.

    Бросает RuntimeError, если middleware ещё не создан (например,
    lifespan запущен до create_app() — это баг конфигурации).
    """
    if _active_requests_instance is None:
        raise RuntimeError(
            "ActiveRequestsMiddleware not initialized. "
            "Ensure create_app() called before app lifespan starts."
        )
    return _active_requests_instance


def reset_active_requests_middleware() -> None:
    """
    Сбросить module-level ссылку.

    Используется в тестах между create_app(), чтобы изолировать
    инстансы.
    """
    global _active_requests_instance
    _active_requests_instance = None


# ═══════════════════════════════════════════════════════════════════════════
# Request ID Header Middleware (опционально, если нужен отдельный header)
# ═══════════════════════════════════════════════════════════════════════════


class RequestIDMiddleware:
    """
    Добавляет X-Request-ID в response (для клиентской трассировки).

    Отличие от correlation_id:
    - correlation_id: для внутренней трассировки в логах.
    - X-Request-ID: для клиента, чтобы он мог сослаться на запрос.

    В нашем случае X-Correlation-ID служит обеим целям, но
    можно добавить отдельный header, если требуется.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name.lower().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cid = correlation_id_var.get()
        if cid is None:
            cid = generate_correlation_id()
            correlation_id_var.set(cid)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers_list = list(message.get("headers", []))
                headers_list.append((self.header_name, cid.encode()))
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_wrapper)
