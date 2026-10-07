#!/usr/bin/env bash
# reaper.sh — периодически останавливает просроченные инстансы заданий.
# Запуск: во втором терминале рядом с ./dev.sh
set -euo pipefail
cd "$(dirname "$0")"

# Читаем .env, чтобы подхватить случайный ADMIN_PASSWORD, сгенерированный
# lan-setup.sh. Если .env нет — используются значения по умолчанию
# (для чисто локального запуска без lan-setup.sh).
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Backend больше не публикует порт 8000 наружу — стучимся через nginx (/api/).
API="${CTF_API_URL:-http://localhost/api}"
USER="${CTF_ADMIN_USER:-${ADMIN_USERNAME:-VasyMinusov}}"
PASS="${CTF_ADMIN_PASS:-${ADMIN_PASSWORD:-0907Seva!!!2003}}"
INTERVAL="${REAP_INTERVAL:-300}"   # секунд между прогонами

get_token() {
  curl -s -X POST "$API/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=$USER" \
    --data-urlencode "password=$PASS" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))'
}

TOKEN=""
echo "[reaper] API=$API, интервал=${INTERVAL}s"
while true; do
  if [ -z "$TOKEN" ]; then
    TOKEN=$(get_token || true)
  fi
  if [ -z "$TOKEN" ]; then
    echo "[reaper] $(date -Iseconds) авторизация не удалась, повтор через $INTERVAL c"
    sleep "$INTERVAL"
    continue
  fi
  RESP=$(curl -s -X POST "$API/admin/instances/reap" \
    -H "Authorization: Bearer $TOKEN" || true)
  if echo "$RESP" | grep -q '"detail"'; then
    TOKEN=""   # вероятно, истёк — сбросим и перелогинимся
  else
    echo "[reaper] $(date -Iseconds) -> $RESP"
  fi
  sleep "$INTERVAL"
done