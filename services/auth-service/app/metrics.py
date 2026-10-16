"""
Prometheus-метрики auth-сервиса.

Две категории:
1. HTTP-метрики (request count, latency) — даёт
   prometheus-fastapi-instrumentator автоматически при
   Instrumentator().instrument(app): http_requests_total,
   http_request_duration_seconds и т.д.

2. Доменные метрики (этот файл) — auth_logins_total, auth_lockouts_total,
   auth_mfa_verifications_total и т.д. Инкрементятся вручную в роутерах.

Дополнительно: http_requests_inprogress — Gauge «активных HTTP-запросов».
Реализован ЗДЕСЬ, а не через Instrumentator(...,
should_instrument_requests_inprogress=True), потому что встроенный
вариант создаёт Gauge в InstrumentatorMiddleware.__init__ — а эта
инстанциация происходит при билде middleware-стека КАЖДОГО app.
В тестах create_app() вызывается многократно → DuplicateTimeseries.

Наш вариант: Gauge создаётся один раз при импорте модуля
(Python кэширует модули), а инкремент/декремент делает
ActiveRequestsMiddleware в app/middleware.py.

Почему не только HTTP-метрики:
- HTTP-метрика скажет «100 запросов на /auth/login с 401», но не
  скажет, что из них 80 — неверный пароль, 15 — пользователь не
  найден, 5 — lockout. А это разные инциденты (brute-force vs
  enumeration vs самоблокировка).
- Доменные метрики позволяют построить алерты на конкретные
  сценарии: auth_lockouts_total{scope="mfa"} резко вырос —
  атака на TOTP.

Метрики — module-level. Регистрируются в дефолтном REGISTRY при
первом импорте. Повторный импорт не создаёт дубликатов (Python
кэширует модули).

ВАЖНО: при тестах счётчики растут в течение сессии (module-level
state). Тесты должны проверять дельта-значения или использовать
уникальные идентификаторы для проверки наличия меток.
"""

from prometheus_client import Counter, Gauge

# ═══════════════════════════════════════════════════════════════════════════
# HTTP (in-progress)
# ═══════════════════════════════════════════════════════════════════════════

# Замена встроенного Instrumentator Gauge. См. docstring модуля.
# Инкрементится в ActiveRequestsMiddleware (app/middleware.py).
http_requests_inprogress = Gauge(
    "http_requests_inprogress",
    "Number of HTTP requests currently in progress.",
)

# ═══════════════════════════════════════════════════════════════════════════
# Login / lockout
# ═══════════════════════════════════════════════════════════════════════════

auth_logins_total = Counter(
    "auth_logins_total",
    "Total login attempts by result.",
    # Метки:
    #   success             — успешный вход (без MFA)
    #   invalid_credentials — неверный пароль
    #   user_not_found      — email не зарегистрирован (generic 401)
    #   locked              — аккаунт заблокирован (423)
    #   mfa_pending         — пароль верный, требуется MFA (200 + mfa_token)
    ["result"],
)

auth_lockouts_total = Counter(
    "auth_lockouts_total",
    "Total lockouts triggered by rate limiter.",
    # Метки:
    #   login — scope="login" (подбор пароля)
    #   mfa   — scope="mfa" (подбор TOTP)
    ["scope"],
)

# ═══════════════════════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════════════════════
#
# ВАЖНО: это СЧЁТЧИКИ СОБЫТИЙ, не «текущее состояние».
#
# Prometheus-практика: считать события Counter'ами, а производные
# величины (rate, sum, diff) — на стороне Prometheus через promql.
# Gauge «активные сессии сейчас» в multi-worker деплое врёт: у каждого
# воркера свой инстанс метрики, scrape попадает на один pod.
#
# Примеры promql:
#   # Скорость создания сессий (rps):
#   rate(auth_sessions_created_total[5m])
#
#   # Скорость ревокаций с разбивкой по причине:
#   sum by (reason) (rate(auth_sessions_revoked_total[5m]))
#
#   # Всплеск revoke по replay — сигнал атаки на refresh-токены:
#   rate(auth_sessions_revoked_total{reason="replay_detected"}[5m]) > 0
#
# ВАЖНО про истечения: сессия, истёкшая по TTL, НЕ помечается revoked=True
# и НЕ инкрементит auth_sessions_revoked_total. Формула
#   created_total - revoked_total
# даёт «неотозванные сессии», а не «активные». Для точного «активных
# сейчас» — используйте postgres_exporter с SQL-запросом из docs/DEPLOY.md.
#
# Зачем тогда счётчики:
#   - rate(created) видит всплеск успешных логинов (credential stuffing,
#     массовый фишинг, brute-force после обхода rate limit).
#   - rate(revoked) видит массовые logout / password-change (инцидент).
#   - Разница — оценка «неотозванных сессий», полезна для трендов.

auth_sessions_created_total = Counter(
    "auth_sessions_created_total",
    "Total sessions created (new login or MFA login).",
)

auth_sessions_revoked_total = Counter(
    "auth_sessions_revoked_total",
    "Total sessions revoked, by reason.",
    # Метки (фиксированный набор — без cardinality explosion):
    #   logout            — явный logout одной сессии
    #   logout_all        — logout со всех устройств
    #   user_revoked      — отзыв сессии пользователем в /sessions
    #   user_revoked_all  — отзыв всех сессий пользователем
    #   admin_revoked     — отзыв сессий администратором через /admin
    #   password_change   — revoke при смене пароля
    #   password_reset    — revoke при сбросе пароля
    #   replay_detected   — revoke всех сессий при replay refresh-токена
    ["reason"],
)

# ═══════════════════════════════════════════════════════════════════════════
# MFA
# ═══════════════════════════════════════════════════════════════════════════

auth_mfa_verifications_total = Counter(
    "auth_mfa_verifications_total",
    "MFA verification attempts by method and result.",
    # Метки:
    #   method — totp | backup
    #   result — success | invalid | locked
    ["method", "result"],
)

auth_mfa_setup_total = Counter(
    "auth_mfa_setup_total",
    "MFA setup operations by result.",
    # Метки:
    #   result — initiated | confirmed | disabled
    ["result"],
)

# ═══════════════════════════════════════════════════════════════════════════
# Tokens
# ═══════════════════════════════════════════════════════════════════════════

auth_token_refresh_total = Counter(
    "auth_token_refresh_total",
    "Refresh-token operations by result.",
    # Метки:
    #   success — успешная ротация
    #   revoked — токен отозван
    #   expired — истёк
    #   replay  — replay detected, все сессии отозваны
    ["result"],
)

# ═══════════════════════════════════════════════════════════════════════════
# Email actions
# ═══════════════════════════════════════════════════════════════════════════

auth_email_actions_total = Counter(
    "auth_email_actions_total",
    "Email action-token operations by action and result.",
    # Метки:
    #   action — verify_email | password_reset
    #   result — sent | quota_exceeded | interval_throttled | confirmed
    ["action", "result"],
)

# ═══════════════════════════════════════════════════════════════════════════
# OAuth2
# ═══════════════════════════════════════════════════════════════════════════

oauth_logins_total = Counter(
    "oauth_logins_total",
    "OAuth login flow events by provider and result.",
    # Метки:
    #   result — initiated            — пользователь отправлен на провайдера
    #            success              — callback → токены выданы
    #            new_user             — callback → создан новый User
    #            existing_user        — callback → найден существующий OAuthAccount
    #            email_already_taken  — email занят обычным пользователем
    #            email_missing        — провайдер не вернул email
    #            invalid_state        — подделан/истёк state
    #            provider_error       — обмен code или userinfo упал
    ["provider", "result"],
)
