"""
Health-check роутер.

Разделение liveness/readiness согласно Kubernetes best practices:
- /health/live  — процесс жив (всегда 200, если приложение отвечает)
- /health/ready — зависимости доступны (503 при недоступности)

ВАЖНО: health check не должен быть тяжёлым. SELECT 1, не COUNT(*).
Timeout на зависимости — 5 секунд. [citation:11]
"""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine
from app.logging_config import get_correlation_id, get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])

# Timeout на проверку зависимости
DB_CHECK_TIMEOUT_SECONDS = 5.0


# ═══════════════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════════════


class HealthCheckResult(BaseModel):
    """Результат проверки одной зависимости."""

    status: str  # "ok" | "error"
    response_time_ms: float | None = None
    message: str | None = None


class LivenessResponse(BaseModel):
    """Ответ liveness-пробы."""

    status: str = "ok"
    timestamp: str
    version: str


class ReadinessResponse(BaseModel):
    """Ответ readiness-пробы."""

    status: str  # "healthy" | "unhealthy"
    timestamp: str
    version: str
    checks: dict[str, HealthCheckResult]
    correlation_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Liveness probe
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Проверяет, что процесс жив. Не проверяет зависимости.",
)
async def liveness() -> LivenessResponse:
    """
    Liveness probe.

    Всегда возвращает 200, если приложение отвечает.
    НЕ проверяет БД/Redis — это задача readiness.

    Kubernetes использует liveness для решения о перезапуске.
    Если liveness проверяет БД, временная недоступность БД
    вызовет перезапуск pod'а — каскадный отказ. [citation:17]
    """
    settings = get_settings()
    return LivenessResponse(
        status="ok",
        timestamp=datetime.now(UTC).isoformat(),
        version=settings.app_name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Readiness probe
# ═══════════════════════════════════════════════════════════════════════════


async def _check_database() -> HealthCheckResult:
    """
    Проверить доступность БД.

    Лёгкий запрос SELECT 1 с timeout 5 секунд.
    """
    start = datetime.now(UTC)
    try:
        engine = get_engine()
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        elapsed = (datetime.now(UTC) - start).total_seconds() * 1000
        return HealthCheckResult(status="ok", response_time_ms=round(elapsed, 2))
    except TimeoutError:
        log.error("db_healthcheck_timeout", timeout=DB_CHECK_TIMEOUT_SECONDS)
        return HealthCheckResult(status="error", message="database timeout")
    except Exception as exc:
        log.error("db_healthcheck_failed", error=str(exc))
        return HealthCheckResult(status="error", message=str(exc))


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Проверяет готовность принимать трафик (зависимости доступны).",
    responses={
        200: {"description": "Ready to serve traffic"},
        503: {"description": "Not ready (dependency unavailable)"},
    },
)
async def readiness(response: Response) -> ReadinessResponse:
    """
    Readiness probe.

    Проверяет БД и возвращает:
    - 200, если все зависимости доступны.
    - 503, если хотя бы одна недоступна.

    Kubernetes использует readiness для решения о направлении трафика.
    При 503 pod убирается из Service endpoints, но НЕ перезапускается. [citation:15]
    """
    settings = get_settings()
    checks: dict[str, HealthCheckResult] = {}

    # ── Проверка БД ───────────────────────────────────────────────────────
    checks["database"] = await _check_database()

    # ── Определение общего статуса ────────────────────────────────────────
    all_healthy = all(c.status == "ok" for c in checks.values())

    if not all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="healthy" if all_healthy else "unhealthy",
        timestamp=datetime.now(UTC).isoformat(),
        version=settings.app_name,
        checks=checks,
        correlation_id=get_correlation_id(),
    )
