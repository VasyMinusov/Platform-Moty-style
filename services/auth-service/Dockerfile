# syntax=docker/dockerfile:1.7

# ═══════════════════════════════════════════════════════════════════════════
# Stage 1: builder
#
# Устанавливаем зависимости в /app/.venv, затем копируем код.
# Слои с зависимостями кэшируются — пересборка при изменении только
# кода приложения идёт быстро.
# ═══════════════════════════════════════════════════════════════════════════
FROM python:3.14-slim AS builder

# ── Build toolchain ────────────────────────────────────────────────────────
#
# На Python 3.14 не у всех пакетов есть готовые wheels. В частности,
# argon2-cffi собирается из sdist через cffi — для этого нужны gcc
# и libffi-dev. Если у пакета wheel для cp314 есть — компилятор не
# используется, но его наличие не мешает.
#
# gcc/build-essential нужны ТОЛЬКО в builder-стадии. Runtime-образ
# остаётся чистым: копируется только .venv и код.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# uv — статический бинарник, копируем из официального образа.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Настройки uv:
#  UV_COMPILE_BYTECODE     — компилировать .pyc (быстрее старт)
#  UV_LINK_MODE=copy       — копировать пакеты, а не hardlink (важно для Docker)
#  UV_PYTHON_DOWNLOADS=never — не качать Python, использовать системный
#  UV_PROJECT_ENVIRONMENT  — куда класть venv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Копируем ТОЛЬКО манифесты — чтобы кэш слоёв срабатывал при изменении кода.
COPY pyproject.toml uv.lock ./

# ── Установка зависимостей ─────────────────────────────────────────────────
#
# `--frozen` требует, чтобы uv.lock был синхронизирован с pyproject.toml.
# Если lock устарел (например, из зависимостей удалили пакет) — сборка
# упадёт с понятной ошибкой, и lock нужно перегенерировать:
#
#     cd services/auth-service
#     uv lock
#     cd ../.. && make rebuild
#
# Если uv на хосте нет — можно сгенерировать lock через Docker:
#
#     docker run --rm \
#         -v "$PWD/services/auth-service:/app" \
#         -w /app \
#         ghcr.io/astral-sh/uv:latest \
#         uv lock
#
# Альтернатива (без --frozen): uv обновит lock прямо внутри контейнера.
# Менее строго (репозиторий не меняется, но каждая сборка заново
# резолвит lock), зато работает без установки uv на хосте.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Копируем код и миграции.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# ═══════════════════════════════════════════════════════════════════════════
# Stage 2: runtime
#
# Минимальный образ без компиляторов и кэшей uv.
# ═══════════════════════════════════════════════════════════════════════════
FROM python:3.14-slim AS runtime

# Runtime-зависимости: только curl (для HEALTHCHECK) и CA-сертификаты.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь (uid/gid = 1000).
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Копируем venv и код из builder'а.
COPY --from=builder --chown=app:app /app/.venv        /app/.venv
COPY --from=builder --chown=app:app /app/app          /app/app
COPY --from=builder --chown=app:app /app/migrations   /app/migrations
COPY --from=builder --chown=app:app /app/alembic.ini  /app/alembic.ini

# PATH активирует venv, PYTHONPATH добавляет /app (чтобы uvicorn нашёл app.main).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# Healthcheck — liveness, не трогает БД.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# Запуск:
#  --proxy-headers                — доверять X-Forwarded-* (за reverse proxy)
#  --no-access-log                — access-логи пишет structlog-middleware
#  --timeout-graceful-shutdown 30 — ждать активные запросы до 30 сек
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--no-access-log", \
     "--timeout-graceful-shutdown", "30"]