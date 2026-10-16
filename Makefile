# ═══════════════════════════════════════════════════════════════════════
# CTF-Platform — инфраструктурный Makefile
#
# Управление стеком: db + auth-db + auth-service + backend + nginx.
# ═══════════════════════════════════════════════════════════════════════
SHELL := /bin/bash
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")
COMPOSE_FILES ?= -f docker-compose.yml
COMPOSE_CMD = $(COMPOSE) $(COMPOSE_FILES)

SERVICE ?= backend
CMD ?= sh
BACKUP_DIR ?= backups
ENV_FILE ?= .env

.PHONY: help
help:
	@echo "CTF-Platform — команды"
	@echo ""
	@echo "  make init          — первичная настройка (.env, шаблон auth-service)"
	@echo "  make env           — создать .env, если его нет"
	@echo "  make fetch-auth    — клонировать auth-service шаблон в services/"
	@echo "  make migrate       — применить миграции CTF-платформы"
	@echo "  make migrate-auth  — применить миграции auth-service"
	@echo ""
	@echo "  make up            — поднять весь стек"
	@echo "  make down          — остановить и удалить контейнеры"
	@echo "  make stop          — остановить без удаления"
	@echo "  make restart       — перезапустить"
	@echo "  make build         — собрать образы"
	@echo "  make rebuild       — пересобрать без кэша"
	@echo "  make update        — pull + rebuild + up"
	@echo ""
	@echo "  make logs          — логи всех сервисов"
	@echo "  make logs-auth     — логи auth-service"
	@echo "  make logs-backend  — логи ctf-backend"
	@echo "  make ps            — статус контейнеров"
	@echo "  make health        — проверить health эндпоинты"
	@echo ""
	@echo "  make shell-backend — sh в ctf-backend"
	@echo "  make shell-auth    — sh в auth-service"
	@echo "  make shell-db      — psql в CTF-БД"
	@echo "  make shell-auth-db — psql в auth-БД"
	@echo ""
	@echo "  make backup        — дамп CTF-БД в backups/"
	@echo "  make backup-auth   — дамп auth-БД в backups/"
	@echo ""
	@echo "  make clean         — down + удалить контейнеры заданий"
	@echo "  make clean-volumes — УДАЛИТЬ volumes (обе БД)"
	@echo "  make reset         — полный сброс и пересборка"
	@echo ""
	@echo "Переменные:"
	@echo "  SERVICE=backend CMD=\"python -c 'print(1)'\"  — для make exec"
	@echo "  AUTH_SERVICE_REPO=<url>                      — репо шаблона"

# ═══════════════════════════════════════════════════════════════════════
# Init
# ═══════════════════════════════════════════════════════════════════════

env:
	@test -f $(ENV_FILE) || ( \
		echo ">>> Создаю .env с секретами"; \
		printf '%s\n' \
			"POSTGRES_PASSWORD=$$(openssl rand -hex 16)" \
			"AUTH_DB_PASSWORD=$$(openssl rand -hex 16)" \
			"AUTH_JWT_SECRET_KEY=$$(openssl rand -hex 32)" \
			"ADMIN_USERNAME=VasyMinusov" \
			"ADMIN_EMAIL=admin@ctf-platform.localhost" \
			"ADMIN_PASSWORD=$$(openssl rand -base64 18 | tr -d '/+=\n' | head -c 20)" \
			"MODERATOR_USERNAME=moderator" \
			"MODERATOR_EMAIL=moderator@ctf-platform.localhost" \
			"MODERATOR_PASSWORD=$$(openssl rand -base64 18 | tr -d '/+=\n' | head -c 20)" \
			"PUBLIC_HOST=localhost" \
			> $(ENV_FILE); \
		echo ">>> .env создан. Сохраните пароли из файла."; \
	)

# Клонирование auth-service шаблона. По умолчанию — ../auth-service
# (ожидается, что шаблон уже склонирован рядом). Если нужен другой
# источник — переопределите AUTH_SERVICE_REPO.
AUTH_SERVICE_REPO ?= ../auth-service
AUTH_SERVICE_DIR ?= services/auth-service

fetch-auth:
	@test -d $(AUTH_SERVICE_DIR) && { \
		echo ">>> $(AUTH_SERVICE_DIR) уже существует, пропускаю"; \
		exit 0; \
	} || true
	@test -d "$(AUTH_SERVICE_REPO)" || { \
		echo "!!! Не найдена папка $(AUTH_SERVICE_REPO)."; \
		echo "    Скопируйте шаблон auth-service вручную:"; \
		echo "    git clone <url> services/auth-service"; \
		exit 1; \
	}
	mkdir -p services
	cp -r "$(AUTH_SERVICE_REPO)" $(AUTH_SERVICE_DIR)
	@echo ">>> auth-service скопирован в $(AUTH_SERVICE_DIR)"
	@echo ">>> Не забудьте создать $(AUTH_SERVICE_DIR)/.env с ENCRYPTION_KEY:"
	@echo "    openssl rand -base64 32"

init: env fetch-auth
	@echo ">>> Init завершён. Дальше:"
	@echo "    1. Проверьте $(AUTH_SERVICE_DIR)/.env (ENCRYPTION_KEY)"
	@echo "    2. make migrate"
	@echo "    3. make up"

# ═══════════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════════

up: env
	$(COMPOSE_CMD) up -d --build
	@echo ">>> Стек поднят: http://localhost/"

down:
	$(COMPOSE_CMD) down --remove-orphans

stop:
	$(COMPOSE_CMD) stop

restart: down up

build:
	$(COMPOSE_CMD) build

rebuild:
	$(COMPOSE_CMD) build --no-cache

update: build up

# ═══════════════════════════════════════════════════════════════════════
# Migrations
# ═══════════════════════════════════════════════════════════════════════

migrate:
	$(COMPOSE_CMD) run --rm backend alembic upgrade head

migrate-auth:
	$(COMPOSE_CMD) run --rm auth-service alembic upgrade head

# ═══════════════════════════════════════════════════════════════════════
# Logs / status
# ═══════════════════════════════════════════════════════════════════════

logs:
	$(COMPOSE_CMD) logs -f --tail=100

logs-auth:
	$(COMPOSE_CMD) logs -f --tail=100 auth-service

logs-auth-db:
	$(COMPOSE_CMD) logs -f --tail=100 auth-db

logs-backend:
	$(COMPOSE_CMD) logs -f --tail=100 backend

ps:
	$(COMPOSE_CMD) ps

health:
	@echo ">>> CTF backend:"; \
	curl -fsS http://localhost/api/health && echo "" || echo "FAILED"; \
	echo ">>> auth-service:"; \
	curl -fsS http://localhost/api/v1/health/live && echo "" || echo "FAILED"

# ═══════════════════════════════════════════════════════════════════════
# Shell / exec
# ═══════════════════════════════════════════════════════════════════════

shell-backend:
	$(COMPOSE_CMD) exec backend sh

shell-auth:
	$(COMPOSE_CMD) exec auth-service sh

shell-db:
	$(COMPOSE_CMD) exec db psql -U ctf -d ctf

shell-auth-db:
	$(COMPOSE_CMD) exec auth-db psql -U auth -d auth

exec:
	$(COMPOSE_CMD) exec $(SERVICE) $(CMD)

# ═══════════════════════════════════════════════════════════════════════
# Backup
# ═══════════════════════════════════════════════════════════════════════

$(BACKUP_DIR):
	@mkdir -p $(BACKUP_DIR)

backup: $(BACKUP_DIR)
	$(COMPOSE_CMD) exec -T db pg_dump -U ctf -d ctf \
		> $(BACKUP_DIR)/ctf_$$(date +%Y%m%d_%H%M%S).sql
	@echo ">>> Дамп CTF-БД сохранён"

backup-auth: $(BACKUP_DIR)
	$(COMPOSE_CMD) exec -T auth-db pg_dump -U auth -d auth \
		> $(BACKUP_DIR)/auth_$$(date +%Y%m%d_%H%M%S).sql
	@echo ">>> Дамп auth-БД сохранён"

# ═══════════════════════════════════════════════════════════════════════
# Clean
# ═══════════════════════════════════════════════════════════════════════

clean: down clean-challenges
	@echo ">>> Контейнеры и сети удалены"

clean-challenges:
	@ids=$$(docker ps -aq -f label=ctf-user -f label=ctf-challenge); \
	if [ -n "$$ids" ]; then \
		echo ">>> Удаляю контейнеры заданий: $$ids"; \
		docker rm -f $$ids; \
	else \
		echo ">>> Контейнеров заданий нет"; \
	fi

clean-volumes:
	@echo "!!! ВНИМАНИЕ: удаляю volumes с данными обеих БД."
	$(COMPOSE_CMD) down -v --remove-orphans

reset: clean-volumes
	$(COMPOSE_CMD) build --no-cache
	$(COMPOSE_CMD) up -d
	@echo ">>> Полный сброс завершён"