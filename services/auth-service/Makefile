# ═══════════════════════════════════════════════════════════════════════════
# Makefile — удобные команды для разработки и деплоя Auth Service.
#
# Разделы:
#   Dev          — локальная разработка
#   Infra        — Postgres + Redis в Docker
#   Docker       — полный стек в контейнерах
#   Systemd      — установка/управление сервисом
#   Quality      — линтеры, тесты, mypy
#   DB           — миграции Alembic
#   Health       — проверка эндпоинтов
#   Admin        — promote_admin CLI
#   Smoke        — smoke-test (curl)
#   Load         — нагрузочный тест (k6)
#   Clean        — очистка кэшей
#
# Использование:
#   make           — показать список команд
#   make help      — то же самое
#   make <target>
# ═══════════════════════════════════════════════════════════════════════════

SHELL := /bin/bash
.DEFAULT_GOAL := help

APP_NAME := fastapi-t
APP_DIR  := /opt/$(APP_NAME)

# Базовый URL для smoke/load-тестов. Переопределяй через:
#   make smoke BASE_URL=https://staging.example.com
#   make load-test-docker BASE_URL=http://host.docker.internal:8000
BASE_URL ?= http://localhost:8000

# ── Цвета для help ─────────────────────────────────────────────────────────
CYAN  := \033[0;36m
GREEN := \033[0;32m
NC    := \033[0m

.PHONY: help
help:  ## Показать этот список
	@echo ""
	@echo "  $(CYAN)Auth Service — команды$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-22s$(NC) %s\n", $$1, $$2}'
	@echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Dev
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: dev
dev:  ## Запустить uvicorn с hot-reload
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-prod
dev-prod:  ## uvicorn с 4 воркерами (без reload) — для load-теста
	@echo "→ Prod-подобный режим: 4 воркера, QueuePool, без reload"
	@echo "   Используй для load-теста. Для разработки — make dev."
	APP_DEBUG=false uv run uvicorn app.main:app \
		--host 0.0.0.0 \
		--port 8000 \
		--workers 4 \
		--no-access-log

.PHONY: install
install:  ## Установить зависимости (uv sync)
	uv sync

.PHONY: shell
shell:  ## Открыть Python-REPL в контексте проекта
	uv run python

# ═══════════════════════════════════════════════════════════════════════════
# Infra (Postgres + Redis в Docker, приложение локально)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: infra-up
infra-up:  ## Поднять Postgres + Redis в Docker
	docker compose up -d postgres redis
	@echo "Postgres: localhost:$${POSTGRES_PORT:-5432}"
	@echo "Redis:    localhost:$${REDIS_PORT:-6379}"

.PHONY: infra-down
infra-down:  ## Остановить инфраструктуру (без удаления volumes)
	docker compose down

.PHONY: infra-reset
infra-reset:  ## Остановить инфраструктуру + УДАЛИТЬ volumes (данные!)
	@echo "⚠  Это удалит все данные Postgres и Redis!"
	@read -p "Продолжить? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker compose down -v; \
		echo "✓ Volumes удалены"; \
	else \
		echo "Отменено"; \
	fi

.PHONY: infra-logs
infra-logs:  ## Логи инфраструктуры
	docker compose logs -f postgres redis

# ═══════════════════════════════════════════════════════════════════════════
# Docker (полный стек в контейнерах)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: docker-build
docker-build:  ## Собрать образ приложения
	docker compose --profile app build app

.PHONY: docker-up
docker-up:  ## Поднять полный стек (postgres + redis + app)
	docker compose --profile app up -d --build

.PHONY: docker-down
docker-down:  ## Остановить полный стек
	docker compose --profile app down

.PHONY: docker-logs
docker-logs:  ## Логи приложения в контейнере
	docker compose --profile app logs -f app

.PHONY: docker-shell
docker-shell:  ## Shell внутри контейнера приложения
	docker compose --profile app exec app bash

.PHONY: docker-dev
docker-dev:  ## Поднять полный стек + pgAdmin
	docker compose --profile app --profile dev up -d --build

# ═══════════════════════════════════════════════════════════════════════════
# Systemd (установка как системного сервиса)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: install-service
install-service:  ## Установить как systemd-сервис (требует sudo)
	@echo "📦 Установка systemd-сервиса..."
	sudo ./deploy/install.sh

.PHONY: uninstall-service
uninstall-service:  ## Удалить systemd-сервис (не трогает /opt/fastapi-t)
	@echo "🗑  Удаление systemd-сервиса..."
	sudo systemctl disable --now $(APP_NAME) || true
	sudo rm -f /etc/systemd/system/$(APP_NAME).service
	sudo systemctl daemon-reload
	@echo "✅ Unit удалён. Директория $(APP_DIR) НЕ тронута."

.PHONY: service-status
service-status:  ## Статус systemd-сервиса
	systemctl status $(APP_NAME) --no-pager

.PHONY: service-restart
service-restart:  ## Перезапустить systemd-сервис
	sudo systemctl restart $(APP_NAME)
	@echo "✓ Перезапущен"

.PHONY: service-stop
service-stop:  ## Остановить systemd-сервис
	sudo systemctl stop $(APP_NAME)
	@echo "✓ Остановлен"

.PHONY: service-start
service-start:  ## Запустить systemd-сервис
	sudo systemctl start $(APP_NAME)
	@echo "✓ Запущен"

.PHONY: service-logs
service-logs:  ## Логи systemd-сервиса (follow)
	journalctl -u $(APP_NAME) -f

.PHONY: service-errors
service-errors:  ## Только ошибки из логов systemd
	journalctl -u $(APP_NAME) -p err --since "1 hour ago"

# ═══════════════════════════════════════════════════════════════════════════
# Quality (линтеры, тесты, mypy)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: lint
lint:  ## Ruff check
	uv run ruff check app/

.PHONY: lint-fix
lint-fix:  ## Ruff check + autofix
	uv run ruff check --fix app/

.PHONY: format
format:  ## Ruff format
	uv run ruff format app/

.PHONY: mypy
mypy:  ## Mypy (strict)
	uv run mypy app/

.PHONY: test
test:  ## Pytest
	uv run pytest

.PHONY: test-cov
test-cov:  ## Pytest с покрытием
	uv run pytest --cov=app --cov-report=html --cov-report=term

.PHONY: test-fuzz
test-fuzz:  ## Fuzz-тесты (Hypothesis, медленно ~1-2 мин)
	uv run pytest -m fuzz -v

.PHONY: check
check: lint mypy test  ## Все проверки: lint + mypy + test

# ═══════════════════════════════════════════════════════════════════════════
# DB (Alembic)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: migrate
migrate:  ## Применить все миграции
	uv run alembic upgrade head

.PHONY: migrate-down
migrate-down:  ## Откатить одну миграцию
	uv run alembic downgrade -1

.PHONY: migrate-new
migrate-new:  ## Создать миграцию (m="сообщение")
	@if [ -z "$(m)" ]; then \
		echo "Использование: make migrate-new m=\"add users table\""; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: migrate-current
migrate-current:  ## Текущая ревизия
	uv run alembic current

.PHONY: migrate-history
migrate-history:  ## История миграций
	uv run alembic history --verbose

# ═══════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: health
health:  ## Проверить health (localhost:8000)
	@echo "→ Liveness:"
	@curl -sS http://localhost:8000/health/live | head -c 300
	@echo
	@echo "→ Readiness:"
	@curl -sS http://localhost:8000/health/ready | head -c 500
	@echo

# ═══════════════════════════════════════════════════════════════════════════
# Admin (CLI)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: promote-admin
promote-admin:  ## Сделать пользователя админом (e=email)
	@if [ -z "$(e)" ]; then \
		echo "Использование: make promote-admin e=admin@example.com"; \
		exit 1; \
	fi
	uv run python -m app.scripts.promote_admin --email $(e)

.PHONY: demote-admin
demote-admin:  ## Снять права админа (e=email)
	@if [ -z "$(e)" ]; then \
		echo "Использование: make demote-admin e=admin@example.com"; \
		exit 1; \
	fi
	uv run python -m app.scripts.promote_admin --email $(e) --demote

# ═══════════════════════════════════════════════════════════════════════════
# Smoke
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: smoke
smoke:  ## Smoke-test против BASE_URL (по умолчанию localhost:8000)
	@# Pre-check: если сервис не отвечает — падаем с понятным сообщением,
	@# а не с невнятным "connection refused" от curl внутри скрипта.
	@curl -fsS "$(BASE_URL)/health/live" >/dev/null 2>&1 || { \
		echo "⚠  Сервис не отвечает на $(BASE_URL)/health/live"; \
		echo ""; \
		echo "   Подними приложение одним из способов:"; \
		echo "     make dev                  # uvicorn на хосте (с hot-reload)"; \
		echo "     make docker-up            # весь стек в Docker"; \
		echo "     make infra-up && make migrate && make dev   # полный dev-цикл"; \
		exit 1; \
	}
	BASE_URL=$(BASE_URL) ./scripts/smoke-test.sh

.PHONY: smoke-docker
smoke-docker:  ## Smoke-test против контейнера (docker compose exec)
	@# Убеждаемся, что app-контейнер запущен.
	@docker compose --profile app ps --format json 2>/dev/null | grep -q '"Service":"app"' \
		|| { \
			echo "⚠  Контейнер app не запущен."; \
			echo "   Запусти: make docker-up"; \
			exit 1; \
		}
	@echo "→ Запускаем smoke внутри app-контейнера..."
	docker compose --profile app exec -T app \
		bash -c "apt-get update -qq && apt-get install -y -qq jq curl >/dev/null 2>&1; \
		         BASE_URL=http://localhost:8000 ./scripts/smoke-test.sh" \
		|| { \
			echo "⚠  Smoke упал. Смотри вывод выше."; \
			exit 1; \
		}

# ═══════════════════════════════════════════════════════════════════════════
# Load (k6)
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: load-test
load-test:  ## Нагрузочный тест (k6, ~1.5 мин)
	@command -v k6 >/dev/null 2>&1 || { \
		echo "⚠  k6 не установлен. Варианты:"; \
		echo "   - Установить: https://grafana.com/docs/k6/latest/set-up/install-k6/"; \
		echo "   - Или использовать Docker: make load-test-docker"; \
		exit 1; \
	}
	@curl -fsS "$(BASE_URL)/health/live" >/dev/null 2>&1 || { \
		echo "⚠  Сервис не отвечает на $(BASE_URL)/health/live"; \
		echo "   Запусти: make dev   или   make docker-up"; \
		exit 1; \
	}
	BASE_URL=$(BASE_URL) k6 run scripts/load-test.js

.PHONY: load-test-docker
load-test-docker:  ## Нагрузочный тест через Docker (без установки k6)
	@# Pre-check: без этого k6 падает с невнятным "connection refused",
	@# и непонятно — это проблема с k6, с сетью или сервис не запущен.
	@curl -fsS "$(BASE_URL)/health/live" >/dev/null 2>&1 || { \
		echo "⚠  Сервис не отвечает на $(BASE_URL)/health/live"; \
		echo ""; \
		echo "   Подними приложение одним из способов:"; \
		echo "     make dev                  # uvicorn на хосте (с hot-reload)"; \
		echo "     make docker-up            # весь стек в Docker"; \
		echo "     make infra-up && make migrate && make dev   # полный dev-цикл"; \
		echo ""; \
		echo "   На macOS/Windows Docker Desktop 'localhost' внутри контейнера —"; \
		echo "   это контейнер, не хост. Используй:"; \
		echo "     make load-test-docker BASE_URL=http://host.docker.internal:8000"; \
		exit 1; \
	}
	@echo "→ k6 через Docker (образ grafana/k6)"
	@echo "   BASE_URL=$(BASE_URL)"
	docker run --rm -i \
		--network=host \
		-v "$(PWD)/scripts:/scripts:ro" \
		-e BASE_URL=$(BASE_URL) \
		grafana/k6 run /scripts/load-test.js

# ═══════════════════════════════════════════════════════════════════════════
# Clean
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: clean
clean:  ## Очистить временные файлы (кэши, .pyc)
	@echo "🧹 Cleaning temporary files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.pyd" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	@rm -rf htmlcov/ .coverage.* 2>/dev/null || true
	@echo "✅ Done."

.PHONY: clean-all
clean-all: clean  ## Полная очистка, включая .venv
	@echo "🧹 Removing .venv..."
	@rm -rf .venv/
	@echo "✅ Done. Run 'uv sync' to recreate."