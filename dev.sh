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

# 3. Ждём, пока backend станет доступен
echo -e "${YELLOW}Ожидание backend...${NC}"
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "${GREEN}Backend готов.${NC}"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo -e "${RED}Backend не ответил за 60 секунд. Проверьте логи: docker compose logs backend${NC}"
    exit 1
  fi
  sleep 2
done

# 4. Синхронизируем челленджи (требуется админ)
echo -e "${YELLOW}Синхронизация челленджей...${NC}"
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin" \
  -d "password=admin123" 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
if [ -n "$TOKEN" ]; then
  curl -s -X POST http://localhost:8000/admin/challenges/sync \
    -H "Authorization: Bearer ${TOKEN}" >/dev/null || true
  echo -e "${GREEN}Челленджи синхронизированы.${NC}"
else
  echo -e "${YELLOW}Не удалось авторизоваться как admin, пропускаем синхронизацию. Она выполнится автоматически при старте backend.${NC}"
fi

# 5. Проверяем, что pnpm есть
if ! command -v pnpm >/dev/null 2>&1; then
  echo -e "${RED}pnpm не найден. Установите pnpm: https://pnpm.io/installation${NC}"
  exit 1
fi

# 6. Запускаем frontend dev-сервер
echo -e "${GREEN}Запуск frontend dev-сервер (pnpm dev)...${NC}"
cd ctf-frontend
VITE_API_URL=http://localhost:8000 pnpm dev &
FRONTEND_PID=$!

echo -e "${GREEN}Frontend PID: $FRONTEND_PID${NC}"
echo -e "${GREEN}Откройте http://localhost:5173${NC}"

wait "$FRONTEND_PID"
