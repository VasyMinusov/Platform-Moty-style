#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Установка Auth Service как systemd-сервиса.
#
# Использование:
#   sudo ./deploy/install.sh
#
# Что делает:
#   1. Создаёт системного пользователя `auth` (если нет)
#   2. Копирует код в /opt/fastapi-t (rsync, без .git/.venv)
#   3. Создаёт .env из .env.example (если нет)
#   4. Устанавливает зависимости через uv sync
#   5. Устанавливает systemd unit и запускает сервис
#
# Требования:
#   - Linux с systemd
#   - uv (https://docs.astral.sh/uv/)
#   - rsync
#   - Postgres и Redis должны быть доступны (в .env)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Конфигурация ───────────────────────────────────────────────────────────
APP_NAME="fastapi-t"
APP_USER="auth"
APP_GROUP="auth"
APP_DIR="/opt/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"

# ── Цвета ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi

log_info()  { echo -e "${BLUE}→${NC} $*"; }
log_ok()    { echo -e "${GREEN}✓${NC} $*"; }
log_warn()  { echo -e "${YELLOW}⚠${NC} $*" >&2; }
log_error() { echo -e "${RED}✗${NC} $*" >&2; }

# ── Проверки ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    log_error "Запусти от root: sudo $0"
    exit 1
fi

if ! command -v systemctl &>/dev/null; then
    log_error "systemctl не найден. Этот скрипт требует systemd."
    exit 1
fi

if ! command -v uv &>/dev/null; then
    log_error "uv не найден."
    echo "  Установи: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v rsync &>/dev/null; then
    log_error "rsync не найден. Установи: apt install rsync"
    exit 1
fi

if [[ ! -f "${REPO_DIR}/pyproject.toml" ]]; then
    log_error "pyproject.toml не найден в ${REPO_DIR}"
    exit 1
fi

# ── Пользователь ───────────────────────────────────────────────────────────
if ! id -u "${APP_USER}" &>/dev/null; then
    log_info "Создаём системного пользователя ${APP_USER}"
    useradd \
        --system \
        --shell /usr/sbin/nologin \
        --user-group \
        --create-home \
        --home-dir "/home/${APP_USER}" \
        "${APP_USER}"
    log_ok "Пользователь ${APP_USER} создан"
else
    log_info "Пользователь ${APP_USER} уже существует"
fi

# ── Директория ─────────────────────────────────────────────────────────────
log_info "Создаём ${APP_DIR}"
mkdir -p "${APP_DIR}"

# ── Копирование кода ───────────────────────────────────────────────────────
log_info "Копируем код в ${APP_DIR}"
rsync -a --delete \
    --exclude='.git' \
    --exclude='.gitignore' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='.mypy_cache' \
    --exclude='.coverage' \
    --exclude='htmlcov' \
    --exclude='.env' \
    --exclude='.idea' \
    --exclude='.vscode' \
    --exclude='node_modules' \
    "${REPO_DIR}/" "${APP_DIR}/"

# Права на директорию — до синхронизации
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
log_ok "Код скопирован"

# ── .env ───────────────────────────────────────────────────────────────────
if [[ ! -f "${APP_DIR}/.env" ]]; then
    log_info "Создаём .env из .env.example"
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    chown "${APP_USER}:${APP_GROUP}" "${APP_DIR}/.env"

    log_warn "═══════════════════════════════════════════════════════════════"
    log_warn "  ОБЯЗАТЕЛЬНО отредактируй ${APP_DIR}/.env:"
    log_warn "    - JWT_SECRET_KEY    (openssl rand -hex 32)"
    log_warn "    - ENCRYPTION_KEY    (openssl rand -base64 32)"
    log_warn "    - POSTGRES_PASSWORD"
    log_warn "═══════════════════════════════════════════════════════════════"
else
    log_info ".env уже существует, не трогаем"
fi

# ── Зависимости ────────────────────────────────────────────────────────────
log_info "Устанавливаем зависимости (uv sync)"
cd "${APP_DIR}"

# Кэш uv держим в директории пользователя, чтобы не засорять /root
sudo -u "${APP_USER}" \
    env HOME="/home/${APP_USER}" \
    uv sync --frozen --no-dev

log_ok "Зависимости установлены"

# ── Systemd unit ───────────────────────────────────────────────────────────
if [[ ! -f "${SCRIPT_DIR}/${APP_NAME}.service" ]]; then
    log_error "Не найден ${SCRIPT_DIR}/${APP_NAME}.service"
    exit 1
fi

log_info "Устанавливаем systemd unit"
cp "${SCRIPT_DIR}/${APP_NAME}.service" "${SERVICE_FILE}"
chmod 644 "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable "${APP_NAME}"
log_ok "Unit установлен и добавлен в автозапуск"

# ── Запуск ─────────────────────────────────────────────────────────────────
log_info "Запускаем сервис"
systemctl restart "${APP_NAME}"

# Дадим секунду на старт
sleep 2

if systemctl is-active --quiet "${APP_NAME}"; then
    log_ok "Сервис запущен"
    echo
    systemctl status "${APP_NAME}" --no-pager --lines=10 || true
else
    log_error "Сервис не запустился. Логи:"
    journalctl -u "${APP_NAME}" --no-pager --lines=30
    exit 1
fi

# ── Финальные шаги ─────────────────────────────────────────────────────────
echo
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✅ Установка завершена${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo
echo "Дальнейшие шаги:"
echo
echo "  1. Проверь .env:"
echo "       sudo nano ${APP_DIR}/.env"
echo "       sudo systemctl restart ${APP_NAME}"
echo
echo "  2. Применяй миграции:"
echo "       cd ${APP_DIR}"
echo "       sudo -u ${APP_USER} HOME=/home/${APP_USER} \\"
echo "           ${APP_DIR}/.venv/bin/alembic upgrade head"
echo
echo "  3. Проверь health:"
echo "       curl http://localhost:8000/health/live"
echo "       curl http://localhost:8000/health/ready"
echo
echo "Управление:"
echo "  systemctl status ${APP_NAME}"
echo "  systemctl restart ${APP_NAME}"
echo "  systemctl stop ${APP_NAME}"
echo "  journalctl -u ${APP_NAME} -f"
echo