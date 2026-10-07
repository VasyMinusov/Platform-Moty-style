#!/usr/bin/env bash
# lan-setup.sh — подготовка платформы для работы в локальной сети (10–15 устройств).
# Запустите один раз ПЕРЕД ./dev.sh. Если IP ноутбука сменился — запустите снова.
# Секреты (.env: JWT_SECRET, POSTGRES_PASSWORD, ADMIN_PASSWORD, MODERATOR_PASSWORD)
# генерируются один раз и НЕ перезаписываются при повторных запусках.
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ── 1. Определяем LAN IP ─────────────────────────────────────────────
detect_lan_ip() {
  local ip
  ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
  [ -n "${ip:-}" ] && echo "$ip" && return
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "${ip:-}" ] && echo "$ip" && return
  ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
  [ -n "${ip:-}" ] && echo "$ip" && return
}

LAN_IP=$(detect_lan_ip || true)
if [ -z "${LAN_IP:-}" ]; then
  echo -e "${RED}Не удалось определить LAN IP. Задайте вручную: LAN_IP=192.168.x.x $0${NC}"
  exit 1
fi
echo -e "${GREEN}LAN IP:${NC} $LAN_IP"

# ── 2. .env: секреты генерируются один раз, PUBLIC_HOST обновляется ──
touch .env

# Установить переменную, не перезаписывая существующую (для секретов).
set_env_once() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    return
  fi
  printf '%s=%s\n' "$key" "$value" >> .env
}

# Установить/перезаписать переменную (для PUBLIC_HOST).
set_env_force() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    grep -v "^${key}=" .env > .env.tmp
    mv .env.tmp .env
  fi
  printf '%s=%s\n' "$key" "$value" >> .env
}

set_env_force PUBLIC_HOST "$LAN_IP"

set_env_once JWT_SECRET "$(openssl rand -hex 32)"
set_env_once POSTGRES_PASSWORD "$(openssl rand -hex 16)"
set_env_once ADMIN_USERNAME "VasyMinusov"
set_env_once ADMIN_PASSWORD "$(openssl rand -base64 24 | tr -d '/+=\n' | head -c 20)"
set_env_once MODERATOR_USERNAME "moderator"
set_env_once MODERATOR_PASSWORD "$(openssl rand -base64 24 | tr -d '/+=\n' | head -c 20)"

ADMIN_PWD_SHOW=$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)
MODERATOR_PWD_SHOW=$(grep '^MODERATOR_PASSWORD=' .env | cut -d= -f2-)

echo -e "${GREEN}Обновлён .env${NC}:"
echo "  PUBLIC_HOST=$LAN_IP"
echo "  JWT_SECRET=<сгенерирован>"
echo "  POSTGRES_PASSWORD=<сгенерирован>"
echo "  ADMIN_USERNAME=VasyMinusov"
echo -e "  ADMIN_PASSWORD=${GREEN}${ADMIN_PWD_SHOW}${NC}"
echo "  MODERATOR_USERNAME=moderator"
echo -e "  MODERATOR_PASSWORD=${GREEN}${MODERATOR_PWD_SHOW}${NC}"
echo
echo -e "${YELLOW}Сохраните пароль админа — он больше не будет показан.${NC}"

# ── 3. Firewall ──────────────────────────────────────────────────────
open_firewall() {
  if command -v ufw >/dev/null 2>&1; then
    echo "ufw: открываю 80, 5173, 30000–30199 (8000 больше НЕ нужен — backend скрыт)"
    sudo ufw allow 80/tcp           || true
    sudo ufw allow 5173/tcp         || true
    sudo ufw allow 30000:30199/tcp  || true
    # Опционально: если нужно закрыть доступ к порту 8000, который мог
    # быть открыт ранее:
    sudo ufw delete allow 8000/tcp  || true
    echo -e "${YELLOW}Внимание: Docker обходит ufw. Если порты не открываются — см. ufw-docker.${NC}"
  elif command -v firewall-cmd >/dev/null 2>&1; then
    echo "firewalld: открываю порты"
    sudo firewall-cmd --add-port=80/tcp --permanent            || true
    sudo firewall-cmd --add-port=5173/tcp --permanent          || true
    sudo firewall-cmd --add-port=30000-30199/tcp --permanent   || true
    sudo firewall-cmd --remove-port=8000/tcp --permanent       || true
    sudo firewall-cmd --reload                                 || true
  else
    echo -e "${YELLOW}ufw/firewalld не найдены. Откройте порты вручную:${NC}"
    echo "  80/tcp, 5173/tcp, 30000-30199/tcp"
    echo "  и закройте 8000/tcp, если он открыт"
  fi
}

if [ "${SKIP_FIREWALL:-0}" != "1" ]; then
  read -r -p "Открыть порты в firewall? [y/N] " ans
  case "${ans:-}" in
    [yY]*) open_firewall ;;
    *) echo "Пропускаю настройку firewall." ;;
  esac
fi

# ── 4. Итог ──────────────────────────────────────────────────────────
echo
echo -e "${GREEN}Готово.${NC} Дальше:"
echo
echo "  1) ./dev.sh                     — поднимает db + backend + nginx + Vite (5173)"
echo "  2) У себя:      http://$LAN_IP:5173"
echo "  3) Коллегам:    http://$LAN_IP:5173"
echo "  4) Ссылки на инстансы backend отдаёт вида:"
echo "        http://$LAN_IP:30001"
echo "        http://$LAN_IP:30002"
echo "     ...их студент открывает со своего устройства."
echo
echo "  Вход в админку: логин VasyMinusov, пароль — см. вывод выше."
echo
echo "Если IP сменился — запустите ./lan-setup.sh снова."