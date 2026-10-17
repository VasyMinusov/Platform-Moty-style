#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

FRONTEND_PID=""

shutdown() {
  echo ""
  echo -e "${YELLOW}Остановка dev-окружения...${NC}"
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi

  # Останавливаем docker compose
  docker compose down --remove-orphans || true

  # Удаляем висящие контейнеры челленджей, созданные backend'ом.
  # Они подключаются к isolated_net и мешают docker compose down её удалить.
  RUNNING_CHALS=$(docker ps -q -f "label=ctf-user" -f "label=ctf-challenge" 2>/dev/null || true)
  if [ -n "$RUNNING_CHALS" ]; then
    echo -e "${YELLOW}Удаляем оставшиеся контейнеры челленджей...${NC}"
    docker rm -f $RUNNING_CHALS >/dev/null || true
  fi

  exit 0
}

trap shutdown INT TERM EXIT

echo -e "${GREEN}=== Dev-окружение CTF Platform ===${NC}"

# 1. Удаляем остатки прошлых запусков
echo -e "${YELLOW}Очистка orphan-контейнеров челленджей...${NC}"
RUNNING_CHALS=$(docker ps -q -f "label=ctf-user" -f "label=ctf-challenge" 2>/dev/null || true)
if [ -n "$RUNNING_CHALS" ]; then
  docker rm -f $RUNNING_CHALS >/dev/null || true
fi

# 2. Поднимаем инфраструктуру (БД, backend, nginx) с пересборкой образов
echo -e "${GREEN}Запуск docker compose (db, backend, nginx)...${NC}"
docker compose up -d --build

# 3. Ждём, пока backend станет доступен.
# Порт 8000 наружу не публикуется (см. docker-compose.yml) — backend доступен
# только внутри platform_net. Поэтому health-check делаем через `docker compose
# exec` внутри самого контейнера, а не через localhost:8000.
echo -e "${YELLOW}Ожидание backend...${NC}"
for i in $(seq 1 30); do
  if docker compose exec -T backend curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "${GREEN}Backend готов.${NC}"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo -e "${RED}Backend не ответил за 60 секунд. Проверьте логи: docker compose logs backend${NC}"
    exit 1
  fi
  sleep 2
done

# 4. Синхронизируем челленджи.
# Логин идёт через nginx (http://localhost/api/...), учётные данные берутся из
# .env — там lan-setup.sh генерирует случайный ADMIN_PASSWORD.
echo -e "${YELLOW}Синхронизация челленджей...${NC}"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
ADMIN_USER="${ADMIN_USERNAME:-VasyMinusov}"
ADMIN_PASS="${ADMIN_PASSWORD:-0907Seva!!!2003}"

TOKEN=$(curl -s -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${ADMIN_USER}" \
  --data-urlencode "password=${ADMIN_PASS}" \
  2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
if [ -n "$TOKEN" ]; then
  curl -s -X POST http://localhost/api/admin/challenges/sync \
    -H "Authorization: Bearer ${TOKEN}" >/dev/null || true
  echo -e "${GREEN}Челленджи синхронизированы.${NC}"
else
  echo -e "${YELLOW}Не удалось авторизоваться как admin, пропускаем синхронизацию. Она выполнится автоматически при старте backend.${NC}"
fi

# 5. Frontend теперь раздаётся через nginx из контейнера frontend.
#    Отдельный Vite-сервер (pnpm dev) больше не нужен.

# 6. Показываем адреса и ждём Ctrl+C
if [ -f .env ]; then
  LAN_IP=$(grep -E '^PUBLIC_HOST=' .env 2>/dev/null | cut -d= -f2- || true)
fi
echo -e "${GREEN}Платформа готова.${NC}"
echo -e "${GREEN}У себя:    http://localhost${NC}"
if [ -n "${LAN_IP:-}" ] && [ "${LAN_IP}" != "localhost" ]; then
  echo -e "${GREEN}Коллегам:  http://${LAN_IP}${NC}"
fi
echo -e "${YELLOW}Ctrl+C — остановить.${NC}"

# Держим скрипт живым, чтобы trap сработал на Ctrl+C.
while true; do sleep 1; done