#!/bin/bash
set -euo pipefail

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Определяем внешний IP
IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$IP" ]; then
  echo -e "${YELLOW}Не удалось определить внешний IP. Используем localhost.${NC}"
  IP="localhost"
fi

echo -e "${GREEN}=== Публичное тестовое окружение ===${NC}"
echo -e "Публичный IP: ${GREEN}$IP${NC}"

# Сохраняем корень проекта
PROJECT_ROOT=$(pwd)

# Создаём временную директорию
TEMP_DIR=$(mktemp -d -t ctf-public-XXXXXX)
echo -e "Временная директория: $TEMP_DIR"

# Функция очистки при выходе
cleanup() {
  echo -e "\n${YELLOW}Остановка и удаление временных файлов...${NC}"
  if [ -f "$TEMP_DIR/docker-compose.yml" ]; then
    docker compose -f "$TEMP_DIR/docker-compose.yml" --project-directory "$PROJECT_ROOT" down --remove-orphans || true
  fi
  rm -rf "$TEMP_DIR"
  echo -e "${GREEN}Очистка завершена.${NC}"
  exit 0
}

trap cleanup INT TERM EXIT

# Создаём временный nginx.conf
mkdir -p "$TEMP_DIR/nginx"
cat > "$TEMP_DIR/nginx/nginx.conf" <<'EOF'
server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://backend:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://frontend:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

# Создаём временный Dockerfile для фронтенда с Node 22
cat > "$TEMP_DIR/Dockerfile.frontend" <<'EOF'
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EOF

# Создаём временный docker-compose.yml
cat > "$TEMP_DIR/docker-compose.yml" <<EOF
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ctf
      POSTGRES_PASSWORD: ctf_password_change_me
      POSTGRES_DB: ctf
    volumes:
      - db_data:/var/lib/postgresql/data
    networks:
      - platform_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ctf -d ctf"]
      interval: 2s
      timeout: 3s
      retries: 15
      start_period: 5s

  backend:
    build: ${PROJECT_ROOT}/backend
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
    environment:
      DATABASE_URL: postgresql+psycopg2://ctf:ctf_password_change_me@db:5432/ctf
      JWT_SECRET: change_me_super_secret
      CHALLENGE_PORT_RANGE_START: "30000"
      CHALLENGE_PORT_RANGE_END: "30999"
      CHALLENGES_DIR: /challenges
      INSTANCE_TTL_SECONDS: "3600"
      DOCKER_NETWORK: "ctf-platform_isolated_net"
      PUBLIC_HOST: ${IP}
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${PROJECT_ROOT}/challenges:/challenges:ro
    depends_on:
      db:
        condition: service_healthy
    networks:
      - platform_net
      - isolated_net

  frontend:
    build:
      context: ${PROJECT_ROOT}/ctf-frontend
      dockerfile: ${TEMP_DIR}/Dockerfile.frontend
    restart: unless-stopped
    networks:
      - platform_net

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - ${TEMP_DIR}/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - backend
      - frontend
    networks:
      - platform_net

networks:
  platform_net:
    driver: bridge
  isolated_net:
    driver: bridge

volumes:
  db_data:
EOF

# Очистка старых контейнеров челленджей
echo -e "${YELLOW}Очистка orphan-контейнеров челленджей...${NC}"
RUNNING_CHALS=$(docker ps -q -f "label=ctf-user" -f "label=ctf-challenge" 2>/dev/null || true)
if [ -n "$RUNNING_CHALS" ]; then
  docker rm -f $RUNNING_CHALS >/dev/null || true
fi

# Запуск docker compose
echo -e "${GREEN}Запуск docker compose из временной директории...${NC}"
docker compose -f "$TEMP_DIR/docker-compose.yml" --project-directory "$PROJECT_ROOT" up -d --build

# Ожидание готовности backend
echo -e "${YELLOW}Ожидание backend...${NC}"
for i in $(seq 1 30); do
  if curl -sf "http://localhost:8000/health" >/dev/null 2>&1; then
    echo -e "${GREEN}Backend готов.${NC}"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo -e "${RED}Backend не ответил за 60 секунд. Проверьте логи.${NC}"
    exit 1
  fi
  sleep 2
done

# Синхронизация заданий
echo -e "${YELLOW}Синхронизация заданий...${NC}"
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin" \
  -d "password=admin123" 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
if [ -n "$TOKEN" ]; then
  curl -s -X POST http://localhost:8000/admin/challenges/sync \
    -H "Authorization: Bearer ${TOKEN}" >/dev/null || true
  echo -e "${GREEN}Челленджи синхронизированы.${NC}"
else
  echo -e "${YELLOW}Не удалось авторизоваться как admin, пропускаем синхронизацию.${NC}"
fi

echo -e "\n${GREEN}✅ Платформа развёрнута для публичного доступа!${NC}"
echo -e "  • Основной URL:    ${GREEN}http://$IP/${NC}"
echo -e "  • API (Swagger):   ${GREEN}http://$IP:8000/docs${NC}"
echo -e "  • Для инстансов заданий используется хост: ${GREEN}$IP${NC}"
echo -e "\nНажмите ${YELLOW}Ctrl+C${NC} для остановки и очистки временных файлов."

while true; do
  sleep 1
done