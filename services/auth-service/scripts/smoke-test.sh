#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Smoke-test для Auth Service.
#
# Что проверяет (end-to-end, через HTTP):
#   1. GET /health/live   → 200
#   2. GET /health/ready  → 200 (БД доступна)
#   3. X-Correlation-ID эхо (клиентский → response)
#   4. POST /auth/register → 201
#   5. POST /auth/login    → 200 (access + refresh + session_id)
#   6. GET  /users/me      → 200 (email совпадает)
#   7. POST /auth/refresh  → 200 (новая пара, session_id тот же)
#   8. POST /auth/logout   → 200
#   9. POST /auth/refresh  (старый токен после logout) → 401
#
# Использование:
#   ./scripts/smoke-test.sh
#   BASE_URL=http://auth.example.com ./scripts/smoke-test.sh
#
# Зависимости:
#   - curl
#   - jq (парсинг JSON)
#
# Exit code:
#   0 — все проверки прошли.
#   1 — упала первая не прошедшая проверка.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API="${BASE_URL}/api/v1"

# Уникальный email — чтобы повторные запуски не падали на 409 Conflict.
RUN_ID="$(date +%s)-${RANDOM}"
EMAIL="smoke-${RUN_ID}@example.com"
USERNAME="smoke_${RUN_ID//-/_}"     # только [a-zA-Z0-9_]
PASSWORD="correct horse battery staple nist"

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

PASS=0
FAIL=0

ok()   { echo -e "  ${GREEN}✓${NC} $*"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $*" >&2; FAIL=$((FAIL + 1)); }
step() { echo -e "\n${BLUE}▶${NC} $*"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# ── Проверка зависимостей ──────────────────────────────────────────────────
command -v curl >/dev/null 2>&1 || die "curl не найден"
command -v jq   >/dev/null 2>&1 || die "jq не найден (apt install jq)"

echo "═══════════════════════════════════════════════════════════════════════"
echo "  Smoke-test: ${BASE_URL}"
echo "  Run ID:     ${RUN_ID}"
echo "═══════════════════════════════════════════════════════════════════════"

# ── Хелперы ────────────────────────────────────────────────────────────────

# assert_status <expected_status> <actual_status> <описание>
assert_status() {
    local expected="$1" actual="$2" desc="$3"
    if [[ "$actual" == "$expected" ]]; then
        ok "$desc (HTTP $actual)"
    else
        fail "$desc — ожидалось HTTP $expected, получено $actual"
        return 1
    fi
}

# assert_nonempty <value> <описание>
assert_nonempty() {
    local value="$1" desc="$2"
    if [[ -n "$value" && "$value" != "null" ]]; then
        ok "$desc"
    else
        fail "$desc — значение пустое"
        return 1
    fi
}

# assert_eq <expected> <actual> <описание>
assert_eq() {
    local expected="$1" actual="$2" desc="$3"
    if [[ "$expected" == "$actual" ]]; then
        ok "$desc"
    else
        fail "$desc — ожидалось '$expected', получено '$actual'"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# 1. Health
# ═══════════════════════════════════════════════════════════════════════════

step "1. Health"
HTTP=$(curl -sS -o /tmp/smoke_live.json -w '%{http_code}' "${BASE_URL}/health/live")
assert_status 200 "$HTTP" "GET /health/live"

HTTP=$(curl -sS -o /tmp/smoke_ready.json -w '%{http_code}' "${BASE_URL}/health/ready")
assert_status 200 "$HTTP" "GET /health/ready"

DB_STATUS=$(jq -r '.checks.database.status // empty' /tmp/smoke_ready.json)
assert_eq "ok" "$DB_STATUS" "database check status"

# ═══════════════════════════════════════════════════════════════════════════
# 2. Correlation ID echo
# ═══════════════════════════════════════════════════════════════════════════

step "2. Correlation ID"
CID_CLIENT="smoke-${RUN_ID}"
CID_RESPONSE=$(
    curl -sS -D - -o /dev/null \
        -H "X-Correlation-ID: ${CID_CLIENT}" \
        "${BASE_URL}/health/live" \
    | tr -d '\r' \
    | awk 'tolower($1) == "x-correlation-id:" {print $2}'
)
assert_eq "$CID_CLIENT" "$CID_RESPONSE" "X-Correlation-ID echoed"

# ═══════════════════════════════════════════════════════════════════════════
# 3. Register
# ═══════════════════════════════════════════════════════════════════════════

step "3. Register"
HTTP=$(
    curl -sS -o /tmp/smoke_register.json -w '%{http_code}' \
        -X POST "${API}/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${EMAIL}\",\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}"
)
assert_status 201 "$HTTP" "POST /auth/register"

USER_ID=$(jq -r '.id // empty' /tmp/smoke_register.json)
assert_nonempty "$USER_ID" "user.id получен"

# ═══════════════════════════════════════════════════════════════════════════
# 4. Login
# ═══════════════════════════════════════════════════════════════════════════

step "4. Login"
HTTP=$(
    curl -sS -o /tmp/smoke_login.json -w '%{http_code}' \
        -X POST "${API}/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}"
)
assert_status 200 "$HTTP" "POST /auth/login"

ACCESS_TOKEN=$(jq -r '.access_token // empty' /tmp/smoke_login.json)
REFRESH_TOKEN=$(jq -r '.refresh_token // empty' /tmp/smoke_login.json)
SESSION_ID=$(jq -r '.session_id // empty' /tmp/smoke_login.json)
assert_nonempty "$ACCESS_TOKEN"  "access_token получен"
assert_nonempty "$REFRESH_TOKEN" "refresh_token получен"
assert_nonempty "$SESSION_ID"    "session_id получен"

# ═══════════════════════════════════════════════════════════════════════════
# 5. GET /users/me
# ═══════════════════════════════════════════════════════════════════════════

step "5. Профиль"
HTTP=$(
    curl -sS -o /tmp/smoke_me.json -w '%{http_code}' \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        "${API}/users/me"
)
assert_status 200 "$HTTP" "GET /users/me"

ME_EMAIL=$(jq -r '.email // empty' /tmp/smoke_me.json)
assert_eq "$EMAIL" "$ME_EMAIL" "email в профиле"

# ═══════════════════════════════════════════════════════════════════════════
# 6. Refresh (ротация)
# ═══════════════════════════════════════════════════════════════════════════

step "6. Refresh (ротация)"
HTTP=$(
    curl -sS -o /tmp/smoke_refresh.json -w '%{http_code}' \
        -X POST "${API}/auth/refresh" \
        -H "Content-Type: application/json" \
        -d "{\"refresh_token\":\"${REFRESH_TOKEN}\"}"
)
assert_status 200 "$HTTP" "POST /auth/refresh"

NEW_ACCESS=$(jq -r '.access_token // empty' /tmp/smoke_refresh.json)
NEW_REFRESH=$(jq -r '.refresh_token // empty' /tmp/smoke_refresh.json)
NEW_SESSION_ID=$(jq -r '.session_id // empty' /tmp/smoke_refresh.json)

assert_nonempty "$NEW_ACCESS"  "новый access_token"
assert_nonempty "$NEW_REFRESH" "новый refresh_token"

if [[ "$NEW_REFRESH" != "$REFRESH_TOKEN" ]]; then
    ok "refresh_token ротировался (старый != новый)"
else
    fail "refresh_token НЕ ротировался"
fi

assert_eq "$SESSION_ID" "$NEW_SESSION_ID" "session_id сохранился при ротации"

# ═══════════════════════════════════════════════════════════════════════════
# 7. Logout
# ═══════════════════════════════════════════════════════════════════════════

step "7. Logout"
HTTP=$(
    curl -sS -o /tmp/smoke_logout.json -w '%{http_code}' \
        -X POST "${API}/auth/logout" \
        -H "Authorization: Bearer ${NEW_ACCESS}" \
        -H "Content-Type: application/json" \
        -d "{\"refresh_token\":\"${NEW_REFRESH}\",\"all_sessions\":false}"
)
assert_status 200 "$HTTP" "POST /auth/logout"

# ═══════════════════════════════════════════════════════════════════════════
# 8. Refresh после logout → 401
# ═══════════════════════════════════════════════════════════════════════════

step "8. Refresh после logout (ожидаем 401)"
HTTP=$(
    curl -sS -o /tmp/smoke_refresh_revoked.json -w '%{http_code}' \
        -X POST "${API}/auth/refresh" \
        -H "Content-Type: application/json" \
        -d "{\"refresh_token\":\"${NEW_REFRESH}\"}"
)
assert_status 401 "$HTTP" "revoked refresh отклонён"

PROBLEM_TYPE=$(jq -r '.type // empty' /tmp/smoke_refresh_revoked.json)
if [[ "$PROBLEM_TYPE" == *"/invalid-token" ]]; then
    ok "problem-type = invalid-token"
else
    fail "ожидался problem-type invalid-token, получен '$PROBLEM_TYPE'"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Итог
# ═══════════════════════════════════════════════════════════════════════════

echo
echo "═══════════════════════════════════════════════════════════════════════"
if [[ $FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}✓ Smoke-test пройден${NC} (${PASS} проверок)"
    echo "═══════════════════════════════════════════════════════════════════"
    exit 0
else
    echo -e "  ${RED}✗ Smoke-test провален${NC} (${PASS} passed, ${FAIL} failed)"
    echo "═══════════════════════════════════════════════════════════════════"
    exit 1
fi