"""
Точка входа auth-сервиса.

Сборка приложения:
- Lifespan: init/dispose ресурсов (БД, HIBP-клиент, crypto, rate limiter)
- Middleware: CORS, Correlation ID, TrustedHost, GZip, ActiveRequests
- Exception handlers: RFC 9457
- Routers: health, auth, email, users, mfa
- OpenAPI: кастомная схема безопасности (Bearer)
- Prometheus /metrics (опционально, с защитой через Bearer)

Все параметры (docs_enabled, cors_*, trusted_hosts, app_version,
metrics_*) читаются из app.config.Settings.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, params, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.config import get_settings
from app.database import dispose_engine, get_engine
from app.exceptions import register_exception_handlers
from app.logging_config import configure_logging, get_logger
from app.middleware import (
    ActiveRequestsMiddleware,
    CorrelationLoggingMiddleware,
    RequestIDMiddleware,
    get_active_requests_middleware,
)
from app.routers import admin, auth, email, health, mfa, oauth, users
from app.security.encryption import get_encryption_service
from app.security.jwt_handler import get_jwt_handler
from app.security.passwords import get_breach_checker, get_dummy_hash
from app.security.rate_limit import (
    init_rate_limiter,
    shutdown_rate_limiter,
)

# ── Логирование настраиваем ДО создания app ─────────────────────────────────
# Иначе первый лог (в т.ч. из FastAPI) пойдёт через дефолтный handler.
configure_logging()

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Graceful shutdown
# ═══════════════════════════════════════════════════════════════════════════

# Сколько секунд ждать завершения активных HTTP-запросов при SIGTERM.
# Должно быть МЕНЬШЕ, чем --timeout-graceful-shutdown у uvicorn (30),
# чтобы мы успели корректно закрыть пулы до того, как uvicorn убьёт
# процесс. Иначе dispose_engine() может не выполниться.
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 25.0


# ═══════════════════════════════════════════════════════════════════════════
# Metrics auth (module-level)
# ═══════════════════════════════════════════════════════════════════════════
#
# HTTPBearer создаётся один раз на процесс, Annotated-тип — как в
# dependencies.py (BearerCreds). Nested closure не работает: mypy strict
# не разрешает Depends() в Annotated внутри функции — "Function
# fastapi.param_functions.Depends is not valid as a type".
#
# Используется только когда settings.metrics_require_auth=True.

_metrics_bearer = HTTPBearer(auto_error=False)

_MetricsCreds = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(_metrics_bearer),
]


async def _verify_metrics_token(credentials: _MetricsCreds) -> None:
    """
    Проверить Bearer-токен для /metrics.

    Активен только при METRICS_REQUIRE_AUTH=true. При неверном токене —
    403 (не 401: токен передан, но не подходит).

    Сравнение токенов — обычное `!=`. Timing-attack здесь не критичен:
    /metrics — не публичный endpoint, атакующий уже должен иметь доступ
    к сети. Плюс metrics_token — долгоживущий секрет с высокой энтропией.
    """
    settings = get_settings()
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics require Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.metrics_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid metrics token.",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Lifespan: init / dispose
# ═══════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Lifespan: startup и shutdown.

    Заменяет @app.on_event("startup"/"shutdown") — event handlers
    deprecated с FastAPI 0.109 и будут удалены в будущих версиях.

    Startup:
    - Прогреваем пул соединений БД (SELECT 1) — ловим проблемы
      конфига сразу, а не на первом запросе.
    - Инициализируем singleton'ы (JWT handler, encryption service,
      breach checker). Это тоже fail-fast: если ключи невалидны,
      сервис не стартует.

    Shutdown (порядок важен):
    1. Ждём завершения активных HTTP-запросов (graceful shutdown).
    2. Закрываем пул БД.
    3. Закрываем HTTP-клиент HIBP (connection pool).
    4. Закрываем соединения rate limiter (Redis, если используется).
    """
    settings = get_settings()

    log.info(
        "app_starting",
        app_name=settings.app_name,
        app_version=settings.app_version,
        env=settings.app_env,
        debug=settings.app_debug,
        docs_enabled=settings.docs_enabled,
        metrics_enabled=settings.metrics_enabled,
    )

    # ── Startup ───────────────────────────────────────────────────────────
    try:
        # Прогрев БД: fail-fast, если БД недоступна.
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("db_connection_ok")

        # Инициализация singleton'ов (fail-fast на невалидном конфиге).
        get_jwt_handler()
        get_encryption_service()
        get_breach_checker()

        # Прогрев timing-safe dummy-хеша: первый hash() занимает ~50–100ms
        # (memory-hard Argon2). Прогреваем на старте, чтобы первый логин
        # несуществующего пользователя не был аномально медленным.
        get_dummy_hash()

        # Rate limiter: в Redis-режиме делает PING — fail-fast при
        # недоступном Redis. В memory-режиме — no-op.
        await init_rate_limiter()

        log.info("security_services_initialized")

    except Exception as exc:
        log.error("app_startup_failed", error=str(exc), exc_info=True)
        raise

    log.info("app_started", api_prefix=settings.api_prefix)

    yield  # ← приложение работает

    # ── Shutdown ──────────────────────────────────────────────────────────
    log.info("app_stopping")

    # ── 1. Graceful shutdown: ждём активные запросы ───────────────────────
    #
    # uvicorn с --timeout-graceful-shutdown 30 при SIGTERM:
    #   a) перестаёт принимать новые соединения;
    #   b) ждёт завершения активных запросов до 30 сек;
    #   c) вызывает lifespan shutdown.
    #
    # Наш wait_for_zero — вторая линия обороны: если запрос «завис»
    # внутри (например, ждёт медленный SQL), мы даём ему 25 сек,
    # а не убиваем сразу. 25 < 30, чтобы dispose_engine() успел
    # выполниться в рамках таймаута uvicorn.
    try:
        active_mw = get_active_requests_middleware()
        drained = await active_mw.wait_for_zero(
            timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
        )
        if drained:
            log.info("graceful_shutdown_complete")
        else:
            log.warning(
                "graceful_shutdown_timeout",
                remaining=active_mw.active_count,
                timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            )
    except RuntimeError as exc:
        # Middleware не инициализирован — это возможно при запуске
        # lifespan без create_app() (например, в unit-тестах с
        # прямым вызовом). Не считаем это фатальным.
        log.warning("graceful_shutdown_skipped", reason=str(exc))

    # ── 2. Закрываем ресурсы ──────────────────────────────────────────────
    try:
        await shutdown_rate_limiter()
        await dispose_engine()
        await get_breach_checker().close()
    except Exception as exc:
        log.error("app_shutdown_error", error=str(exc))

    log.info("app_stopped")


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI app
# ═══════════════════════════════════════════════════════════════════════════


def create_app() -> FastAPI:
    """
    Фабрика приложения.

    Фабрика (а не module-level app) — best practice:
    - Тесты могут создавать изолированные инстансы.
    - Легче переопределять конфигурацию.
    """
    settings = get_settings()

    # FastAPI 0.141+ сам сериализует данные через Pydantic (~2-3x быстрее,
    # чем ORJSONResponse). Параметр default_response_class убран —
    # см. https://fastapi.tiangolo.com/advanced/custom-response/
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Auth service with NIST SP 800-63B Rev 4 compliance.\n\n"
            "**Security**: Argon2id, HIBP blocklist, rate limiting, "
            "JWT with rotation, ГОСТ-криптография для сертифицированных контуров."
        ),
        lifespan=lifespan,
        # docs_enabled=False в prod (защита от enumeration).
        # Логика: Settings.docs_enabled → False в prod, True в dev,
        # но можно переопределить через OPENAPI_DOCS_ENABLED=true.
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        openapi_tags=[
            {"name": "health", "description": "Liveness / readiness probes"},
            {"name": "auth", "description": "Регистрация, вход, refresh, logout"},
            {"name": "users", "description": "Профиль и управление сессиями"},
            {"name": "mfa", "description": "Управление MFA (TOTP)"},
            {"name": "admin", "description": "Операционные действия (требует MFA)"},
        ],
    )

    # ── Middleware ────────────────────────────────────────────────────────
    #
    # Порядок: последний добавленный — outermost.
    # На request path: Correlation → ActiveRequests → RequestID → GZip →
    # TrustedHost → CORS → route.
    #
    # ВАЖНО: CorrelationLoggingMiddleware должен быть outermost,
    # чтобы correlation_id устанавливался до всех остальных.
    #
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
        max_age=settings.cors_max_age,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # TrustedHost — только в prod (в dev работаем с localhost)
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts,
        )

    # ActiveRequestsMiddleware — инкремент/декремент Gauge
    # http_requests_inprogress + счётчик для graceful shutdown.
    # Заменяет встроенный механизм prometheus-fastapi-instrumentator
    # (см. _setup_metrics).
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(ActiveRequestsMiddleware)
    app.add_middleware(CorrelationLoggingMiddleware)  # outermost

    # ── Exception handlers ────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────────────────
    #
    # Health: без API-префикса — Kubernetes probe'ы обычно бьют в
    # /health/* напрямую, без версии.
    #
    app.include_router(health.router)

    # API v1: с префиксом /api/v1
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(email.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)
    app.include_router(mfa.router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)

    # OAuth монтируется УСЛОВНО: в сертифицированном контуре фича
    # обычно запрещена, и мы не должны даже раскрывать её наличие
    # в OpenAPI. Отсутствие в стеке = 404, отсутствие в схеме.
    if settings.oauth_enabled:
        app.include_router(oauth.router, prefix=settings.api_prefix)
        log.info("oauth_router_mounted", prefix=f"{settings.api_prefix}/auth/oauth")
    else:
        log.info("oauth_router_skipped", reason="OAUTH_ENABLED=false")

    # ── OpenAPI customization ─────────────────────────────────────────────
    _customize_openapi(app)

    # ── Prometheus /metrics ───────────────────────────────────────────────
    _setup_metrics(app)

    return app


# ═══════════════════════════════════════════════════════════════════════════
# OpenAPI: Bearer security scheme
# ═══════════════════════════════════════════════════════════════════════════


def _customize_openapi(app: FastAPI) -> None:
    """
    Кастомизация OpenAPI-схемы.

    Добавляет:
    - securitySchemes: BearerAuth (JWT)
    - security: глобальное требование Bearer для всех endpoints,
      кроме health и OAuth-flow (публичные).
    """
    settings = get_settings()

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )

        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "JWT access token. Format: `Bearer <token>`. Obtain via POST /api/v1/auth/login"
                ),
            }
        }

        # Публичные пути — без Bearer в OpenAPI.
        # /health/* — K8s probes.
        # /api/v1/auth/oauth/* — OAuth-flow должен быть публичным
        # (пользователь в браузере, у него ещё нет Bearer).
        oauth_prefix = f"{settings.api_prefix}/auth/oauth"
        for path, path_item in schema["paths"].items():
            if path.startswith("/health") or path.startswith(oauth_prefix):
                continue
            for method in ("get", "post", "patch", "delete", "put"):
                if method in path_item:
                    path_item[method].setdefault("security", [{"BearerAuth": []}])

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


# ═══════════════════════════════════════════════════════════════════════════
# Prometheus /metrics
# ═══════════════════════════════════════════════════════════════════════════


def _setup_metrics(app: FastAPI) -> None:
    """
    Настроить /metrics (Prometheus).

    Две части:
    1. HTTP-метрики — Instrumentator добавляет middleware и endpoint
       с http_requests_total, http_request_duration_seconds и т.д.
    2. Доменные метрики — регистрируются при импорте app.metrics,
       инкрементятся вручную в роутерах.

    Защита:
    - metrics_enabled=False → endpoint не регистрируется.
    - metrics_require_auth=True → требуется Bearer-токен
      (metrics_token из Settings). Проверка — через _verify_metrics_token
      (module-level, см. выше).

    /metrics исключён из OpenAPI (include_in_schema=False) — это
    служебный endpoint, не часть публичного API.

    ВАЖНО: should_instrument_requests_inprogress=False.

    Встроенный Gauge http_requests_inprogress создаётся в
    InstrumentatorMiddleware.__init__ — а этот __init__ вызывается
    на билд middleware-стека КАЖДОГО FastAPI app. В тестах
    create_app() вызывается многократно → DuplicateTimeseries на
    Gauge в дефолтном CollectorRegistry.

    Наша реализация: module-level Gauge в app/metrics.py (создаётся
    один раз при импорте — Python кэширует модули) +
    ActiveRequestsMiddleware в app/middleware.py (inc/dec).
    """
    settings = get_settings()

    if not settings.metrics_enabled:
        log.info("metrics_disabled")
        return

    # ── Опциональная защита ───────────────────────────────────────────────
    dependencies: list[params.Depends] = []
    if settings.metrics_require_auth:
        if not settings.metrics_token:
            # Fail-fast: если защита включена, но токена нет —
            # это ошибка конфигурации. Падать надо на старте.
            raise RuntimeError(
                "METRICS_REQUIRE_AUTH=true, but METRICS_TOKEN is not set. "
                "Generate: openssl rand -hex 32"
            )
        dependencies.append(Depends(_verify_metrics_token))

    # ── Instrumentator ────────────────────────────────────────────────────
    instrumentator = Instrumentator(
        # ВАЖНО: False — см. docstring выше. Наша замена —
        # ActiveRequestsMiddleware + module-level Gauge в app/metrics.py.
        should_instrument_requests_inprogress=False,
        # Исключаем сам /metrics и health-probes из HTTP-метрик:
        # иначе scrape и kubelet засоряют http_requests_total.
        excluded_handlers=["/metrics", "/health/.*"],
    )
    instrumentator.instrument(app)
    instrumentator.expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
        dependencies=dependencies,
    )

    log.info(
        "metrics_enabled",
        endpoint="/metrics",
        require_auth=settings.metrics_require_auth,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Module-level app (для uvicorn)
# ═══════════════════════════════════════════════════════════════════════════

app = create_app()


# ═══════════════════════════════════════════════════════════════════════════
# CLI entrypoint
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug and not settings.is_production,
        log_config=None,  # structlog настраивает логирование сам
        access_log=False,  # access логируется в middleware
        proxy_headers=True,  # доверять X-Forwarded-* (за reverse proxy)
        forwarded_allow_ips="*" if not settings.is_production else None,
        timeout_graceful_shutdown=30,
    )
