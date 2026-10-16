# Auth Service

Сервис аутентификации и авторизации на FastAPI с поддержкой NIST SP 800-63B Rev 4 и ГОСТ-криптографии для сертифицированных контуров.

## Содержание

- [Интеграция в проекты](docs/INTEGRATION.md)
- [API Reference](docs/API.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Расширения](docs/EXTENSIONS.md)
- [Деплой](deploy/DEPLOY.md)
- [Стек](#стек)
- [Что в шаблоне из коробки](#что-в-шаблоне-из-коробки)
- [Что доработать под проект](#что-доработать-под-проект)
- [Требования](#требования)
- [Быстрый старт](#быстрый-старт)
- [Конфигурация](#конфигурация)
- [API](#api)
- [Безопасность](#безопасность)
- [Разработка](#разработка)
- [Миграции](#миграции)
- [Тестирование](#тестирование)
- [Структура проекта](#структура-проекта)
- [Соответствие стандартам](#соответствие-стандартам)
- [Troubleshooting](#troubleshooting)

---

## Стек

| Компонент | Технология | Обоснование |
|---|---|---|
| Web framework | FastAPI 0.141+ | Async, OpenAPI из коробки, dependency injection |
| ASGI server | Uvicorn | Production-ready, uvloop, HTTP/1.1 + HTTP/2 |
| ORM | SQLAlchemy 2.0 (async) | Типизация через `Mapped[T]`, async API |
| БД | PostgreSQL 16+ | asyncpg, JSONB, `TIMESTAMPTZ` |
| Валидация | Pydantic v2 | Rust-core, быстрее v1 в 5-20x |
| Пароли | Argon2id (argon2-cffi) | Memory-hard, победитель PHC 2015 |
| MFA | pyotp (RFC 6238) | TOTP, Google Authenticator / Authy / 1Password |
| JWT | python-jose + gostcrypto | ГОСТ Р 34.10-2012, HS256, ES256 |
| OAuth2 | httpx | Яндекс ID (опционально, `OAUTH_ENABLED`) |
| Rate limiting | Redis (`redis[hiredis]`) | Distributed lockout + quota |
| Логирование | structlog | JSON в prod, console в dev, contextvars |
| Метрики | prometheus-fastapi-instrumentator | HTTP-метрики + доменные Counter'ы |
| Пакетный менеджер | uv | Замена pip + venv + pip-tools, 10-100x быстрее |
| Миграции | Alembic | Автогенерация из SQLAlchemy-моделей |

---

## Что в шаблоне из коробки

- **NIST SP 800-63B Rev 4** — парольная политика без composition rules,
  HIBP-скрининг, rate limiting на все auth-эндпоинты, session
  management с ротацией refresh.
- **MFA (TOTP)** — полный lifecycle: `setup` → `verify` → `login` →
  `disable`, 10 backup-кодов (HMAC-SHA256, одноразовые), replay protection
  (§5.1.2).
- **Email** — подтверждение адреса и сброс пароля. Токены одноразовые
  (HMAC-хеш в БД), инвалидация предыдущего при новом запросе, anti-enumeration
  (generic 200 + timing-safe).
- **Сессии** — `GET /users/me/sessions`, revoke одной / всех, replay
  detection (все сессии отзываются при повторном использовании refresh).
- **Admin-эндпоинты** — `unlock`, `revoke-sessions`, пагинированный audit.
  Требуют MFA. 404 (не 403) для не-админов — anti-enumeration.
- **Rate limit scopes** — изоляция `login` / `mfa` / `verify` / `reset` /
  `reset_interval`. Подбор пароля и подбор TOTP не влияют друг на друга.
- **Наблюдаемость** — `/metrics` (Prometheus), correlation_id через
  contextvars, `audit_logs` с JSONB-метаданными и GIN-индексом.
- **Graceful shutdown** — drain активных запросов перед закрытием пулов.
- **ГОСТ-криптография** — AES-GCM (fallback) + ГОСТ Р 34.12-2015
  («Кузнечик», CFB по Р 34.13-2015), ГОСТ Р 34.10-2012 для JWT.
- **OAuth2 (опционально)** — вход через Яндекс ID. Включается флагом
  `OAUTH_ENABLED=true`; при `false` роутер не монтируется, `/auth/oauth/*`
  → 404, эндпоинтов нет в OpenAPI. По умолчанию **выключен** — для
  защищённого контура (ГОСТ/ФСБ).

## Что доработать под проект

См. [`docs/EXTENSIONS.md`](docs/EXTENSIONS.md) — рецепты:

- OAuth2 — Яндекс реализован; Google / GitHub / свой OAuth2-провайдер — рецепт.
- WebAuthn (FIDO2).
- SAML (для B2B).
- M2M: API-ключи.
- Multi-tenancy (tenant_id + RLS).
- OpenTelemetry (трассировка).
- Vault / HSM для мастер-ключей.
- Introspect endpoint (RFC 7662) или Redis blacklist для мгновенного
  отзыва access-токенов.
- S3 / SES вместо SMTP.

---

## Требования

- **Python 3.14+**
- **PostgreSQL 16+** (для локальной разработки — через docker-compose)
- **Redis 7+** — для `RATE_LIMIT_BACKEND=redis` (обязательно в prod)
- **uv** — [установка](https://docs.astral.sh/uv/getting-started/installation/)
- **OpenSSL** — для генерации ключей

---

## Быстрый старт

### 1. Клонирование и установка

```bash
git clone git@github.com:VasyMinusov/fastapi-t.git
cd fastapi-t
uv sync
```

### 2. Настройка окружения

```bash
cp .env.example .env

# Сгенерировать секреты:
openssl rand -hex 32     # → JWT_SECRET_KEY
openssl rand -base64 32  # → ENCRYPTION_KEY
openssl rand -hex 32     # → METRICS_TOKEN (если METRICS_REQUIRE_AUTH=true)
```

Вставить в `.env`:

```env
JWT_SECRET_KEY=<вывод openssl rand -hex 32>
ENCRYPTION_KEY=<вывод openssl rand -base64 32>
```

### 3. Запуск инфраструктуры

```bash
docker compose up -d postgres redis
```

### 4. Миграции

```bash
uv run alembic upgrade head
```

### 5. Запуск

```bash
uv run uvicorn app.main:app --reload
```

Открыть http://localhost:8000/docs.

### 6. Первый админ

Зарегистрировать пользователя через `/api/v1/auth/register`, включить
ему MFA (`/users/me/mfa/setup` → `/verify`), затем:

```bash
make promote-admin e=admin@example.com
```

Подробности — [`deploy/DEPLOY.md`](deploy/DEPLOY.md) → §2.11.

### 7. Проверка

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

---

## Конфигурация

Все переменные читаются через `app/config.py:Settings` из `.env` и env-переменных. Env-переменные имеют приоритет над `.env`.

### Обязательные

| Переменная | Описание | Пример |
|---|---|---|
| `JWT_SECRET_KEY` | Секрет для подписи JWT, ≥32 символа | `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | 32 байта в base64 для AES-GCM | `openssl rand -base64 32` |

### App

| Переменная | Дефолт | Описание |
|---|---|---|
| `APP_NAME` | `Auth Service` | Название в OpenAPI и письмах |
| `APP_ENV` | `local` | `local` / `dev` / `stage` / `prod` |
| `APP_DEBUG` | `true` | Debug-режим (reload, docs) |
| `APP_HOST` | `0.0.0.0` | Bind-адрес |
| `APP_PORT` | `8000` | Порт |
| `API_PREFIX` | `/api/v1` | Префикс для API |

### Logging

| Переменная | Дефолт | Описание |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `LOG_FORMAT` | `json` | `json` (prod) / `console` (dev) |

### Database

| Переменная | Дефолт | Описание |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Хост БД |
| `POSTGRES_PORT` | `5432` | Порт БД |
| `POSTGRES_USER` | `auth_user` | Пользователь БД |
| `POSTGRES_PASSWORD` | `change_me` | Пароль БД |
| `POSTGRES_DB` | `auth_db` | Имя БД |
| `DB_POOL_SIZE` | `10` | Размер пула соединений |
| `DB_MAX_OVERFLOW` | `20` | Max overflow пула |
| `DB_POOL_RECYCLE` | `3600` | Время жизни соединения (сек) |
| `DB_ECHO` | `false` | SQL-логирование |

### Redis

| Переменная | Дефолт | Описание |
|---|---|---|
| `REDIS_HOST` | `localhost` | Хост Redis |
| `REDIS_PORT` | `6379` | Порт |
| `REDIS_DB` | `0` | Номер БД |
| `REDIS_PASSWORD` | `null` | Пароль (если требуется) |
| `REDIS_SSL` | `false` | Использовать TLS |

### JWT

| Переменная | Дефолт | Описание |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | `HS256` / `ES256` / `GOST3410-2012-256` / `GOST3410-2012-512` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Время жизни access |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Время жизни refresh |
| `JWT_ISSUER` | `auth-service` | Issuer claim |
| `JWT_AUDIENCE` | `auth-service` | Audience claim |
| `JWT_PUBLIC_KEY` | `null` | PEM публичного ключа (ES256) — для JWKS |
| `JWT_KEY_ID` | `null` | Явный `kid` (иначе RFC 7638 thumbprint) |

### MFA

| Переменная | Дефолт | Описание |
|---|---|---|
| `MFA_TOTP_ISSUER` | `Auth Service` | Issuer в Google Authenticator |
| `MFA_TEMP_TOKEN_EXPIRE_SECONDS` | `300` | TTL `mfa_token` (5 мин) |
| `MFA_BACKUP_CODES_COUNT` | `10` | Число backup-кодов |
| `MFA_TOTP_VALID_WINDOW` | `1` | Окно TOTP (±30 сек) |

### Encryption

| Переменная | Дефолт | Описание |
|---|---|---|
| `ENCRYPTION_KEY` | — | base64 32 байта (обязательно) |
| `KEY_PROVIDER` | `env` | `env` / `vault` (Vault — заглушка) |
| `VAULT_ADDR` | `null` | Только для `KEY_PROVIDER=vault` |
| `VAULT_TOKEN` | `null` | Только для `KEY_PROVIDER=vault` |

### OAuth2 (опционально)

| Переменная | Дефолт | Описание |
|---|---|---|
| `OAUTH_ENABLED` | `false` | Включить OAuth-роутер. `false` → `/auth/oauth/*` = 404 |
| `OAUTH_YANDEX_CLIENT_ID` | `null` | Client ID из консоли Яндекс ID |
| `OAUTH_YANDEX_CLIENT_SECRET` | `null` | Client Secret |
| `OAUTH_STATE_TTL_SECONDS` | `300` | TTL подписанного state (CSRF) |
| `OAUTH_PUBLIC_BASE_URL` | `http://localhost:8000` | Публичный URL сервиса (для redirect_uri) |
| `OAUTH_FRONTEND_CALLBACK_URL` | `http://localhost:3000/oauth/callback` | Куда редиректим после callback |

**Регистрация приложения в Яндексе:** https://oauth.yandex.ru/client/new
Redirect URI в консоли провайдера должен **точно** совпадать с:
`{OAUTH_PUBLIC_BASE_URL}/api/v1/auth/oauth/yandex/callback`

### Rate limiting

| Переменная | Дефолт | Описание |
|---|---|---|
| `RATE_LIMIT_BACKEND` | `memory` | `memory` (dev) / `redis` (prod) |
| `RATE_LIMIT_MAX_ATTEMPTS` | `10` | Login: попыток до lockout |
| `RATE_LIMIT_LOCKOUT_SECONDS` | `300` | Login: базовый lockout (5 мин) |
| `RATE_LIMIT_REDIS_TTL` | `900` | TTL записей в Redis |
| `RATE_LIMIT_MAX_LOCKOUT_SECONDS` | `86400` | Hard cap backoff (24 ч) |
| `RATE_LIMIT_MFA_VERIFY_MAX_ATTEMPTS` | `5` | MFA: попыток до lockout |
| `RATE_LIMIT_MFA_VERIFY_LOCKOUT_SECONDS` | `900` | MFA: базовый lockout (15 мин) |
| `RATE_LIMIT_EMAIL_PER_HOUR` | `3` | Quota писем в час |
| `RATE_LIMIT_PASSWORD_RESET_MIN_INTERVAL_SECONDS` | `60` | Мин. интервал между письмами сброса |

### Breach check (HIBP)

| Переменная | Дефолт | Описание |
|---|---|---|
| `HIBP_ENABLED` | `true` | Проверка пароля по HIBP |
| `HIBP_TIMEOUT_SECONDS` | `5.0` | Таймаут запроса |
| `HIBP_FAIL_OPEN` | `true` | Пропускать при недоступности HIBP |

### CORS и TrustedHost

| Переменная | Дефолт | Описание |
|---|---|---|
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON-массив разрешённых origin'ов |
| `CORS_ALLOW_CREDENTIALS` | `true` | Разрешить cookies |
| `CORS_MAX_AGE` | `600` | Preflight cache (сек) |
| `TRUSTED_HOSTS` | `["*"]` | JSON-массив (prod — конкретные домены) |

### OpenAPI

| Переменная | Дефолт | Описание |
|---|---|---|
| `OPENAPI_DOCS_ENABLED` | `true` | В prod — `false` (защита от enumeration) |

### Metrics

| Переменная | Дефолт | Описание |
|---|---|---|
| `METRICS_ENABLED` | `true` | Включить `/metrics` |
| `METRICS_REQUIRE_AUTH` | `false` | Требовать Bearer для `/metrics` |
| `METRICS_TOKEN` | `null` | Токен (обязателен при `METRICS_REQUIRE_AUTH=true`) |

### Email

| Переменная | Дефолт | Описание |
|---|---|---|
| `FRONTEND_URL` | `http://localhost:3000` | Для ссылок в письмах |
| `EMAIL_VERIFICATION_TOKEN_TTL_SECONDS` | `86400` | TTL verify-токена (24 ч) |
| `PASSWORD_RESET_TOKEN_TTL_SECONDS` | `3600` | TTL reset-токена (1 ч) |
| `SMTP_HOST` | `""` | Пусто = no-op (письма логируются) |
| `SMTP_PORT` | `587` | Порт SMTP |
| `SMTP_USER` | `""` | Логин SMTP |
| `SMTP_PASSWORD` | `""` | Пароль SMTP |
| `SMTP_START_TLS` | `true` | STARTTLS |
| `SMTP_TIMEOUT_SECONDS` | `10.0` | Таймаут SMTP |
| `EMAIL_FROM` | `noreply@localhost` | Отправитель |

### Профили по `APP_ENV`

| | `local` / `dev` | `prod` |
|---|---|---|
| `/docs`, `/redoc` | Включены | Отключены |
| `LOG_FORMAT` | `console` | `json` |
| JWT-алгоритм | `HS256` | `GOST3410-2012-256` |
| TrustedHost | Нет | Да |
| SQL echo | `INFO` | `WARNING` |
| `reload` | Да | Нет |
| `OAUTH_ENABLED` | `true` (dev) | `false` (default, вкл. явно) |

---

## API

Базовый префикс: `/api/v1` (кроме `/health/*`).

### Health

```
GET /health/live      → 200 LivenessResponse (всегда, если процесс жив)
GET /health/ready     → 200 ReadinessResponse | 503 (проверка БД)
```

### Auth

```
POST /api/v1/auth/register              → 201 UserRead
POST /api/v1/auth/login                 → 200 TokenResponse | MFAPendingResponse
POST /api/v1/auth/mfa/verify            → 200 TokenResponse
POST /api/v1/auth/refresh               → 200 TokenResponse
POST /api/v1/auth/logout                → 200 MessageResponse
POST /api/v1/auth/verify-email          → 200 MessageResponse
POST /api/v1/auth/verify-email/confirm  → 200 MessageResponse
POST /api/v1/auth/password-reset/request → 200 MessageResponse
POST /api/v1/auth/password-reset/confirm → 200 MessageResponse
```

### OAuth2 (только при `OAUTH_ENABLED=true`)

```
GET /api/v1/auth/oauth/providers              → 200 list[OAuthProviderRead]
GET /api/v1/auth/oauth/{provider}/authorize   → 302 на провайдера
GET /api/v1/auth/oauth/{provider}/callback    → 302 на frontend с токенами
```

Все три эндпоинта **публичные** (без Bearer) — пользователь в браузере,
у него ещё нет access-токена. При `OAUTH_ENABLED=false` роутер не
монтируется: любой `/auth/oauth/*` → 404, эндпоинтов нет в OpenAPI.

### Users

```
GET    /api/v1/users/me                → 200 UserRead
PATCH  /api/v1/users/me                → 200 UserRead
POST   /api/v1/users/me/password       → 200 MessageResponse (требует MFA)
GET    /api/v1/users/me/sessions       → 200 list[SessionRead]
DELETE /api/v1/users/me/sessions/{sid} → 200 MessageResponse
DELETE /api/v1/users/me/sessions       → 200 MessageResponse
```

### MFA

```
POST /api/v1/users/me/mfa/setup    → 200 MFASetupResponse
POST /api/v1/users/me/mfa/verify   → 200 MFAVerifySetupResponse (backup-коды)
POST /api/v1/users/me/mfa/disable  → 200 MessageResponse
```

### Admin (требует MFA)

```
GET    /api/v1/admin/users/{id}                 → 200 UserRead
POST   /api/v1/admin/users/{id}/unlock          → 200 MessageResponse
POST   /api/v1/admin/users/{id}/revoke-sessions → 200 MessageResponse
GET    /api/v1/admin/users/{id}/audit           → 200 PaginatedResponse[AuditLogRead]
```

### Аутентификация

Все endpoints, кроме `/health/*`, `/auth/register`, `/auth/login`, `/auth/mfa/verify`, `/auth/verify-email/confirm`, `/auth/password-reset/*`,
`/auth/oauth/*` (при `OAUTH_ENABLED=true`), требуют заголовок:

```
Authorization: Bearer <access_token>
```

Access-токен живёт 15 минут. Обновляется через `/auth/refresh` с refresh-токеном.

### Формат ошибок

Все ошибки — [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457):

```json
{
  "type": "https://api.auth-service.local/problems/authentication-failed",
  "title": "Authentication Failed",
  "status": 401,
  "detail": "Invalid credentials.",
  "instance": "/api/v1/auth/login",
  "correlation_id": "a1b2c3d4"
}
```

Media type: `application/problem+json`.

Полный список problem-type — [`docs/API.md`](docs/API.md) → Errors.

### Correlation ID

Каждый запрос получает correlation ID:

- Извлекается из `X-Correlation-ID` (если клиент передал).
- Иначе генерируется (8 hex-символов).
- Возвращается в ответе в `X-Correlation-ID`.
- Попадает во все логи и в `audit_logs.correlation_id`.

```bash
curl -H "X-Correlation-ID: my-trace-123" http://localhost:8000/health/live
```

---

## Безопасность

### Пароли

**Хеширование**: Argon2id, параметры — `time_cost=3, memory_cost=64MiB, parallelism=4, hash_len=32, salt_len=16`.

**Политика (NIST SP 800-63B Rev 4)**:

- Минимум **15** символов для single-factor (AAL1).
- Минимум **8** символов при использовании MFA.
- Максимум 64 символа.
- **Нет** composition rules.
- **Нет** периодической ротации.
- **Есть** blocklist screening через HIBP Pwned Passwords (k-anonymity).
- **Есть** запрет на username/email в пароле.

**Прозрачное обновление**: при успешном login, если `needs_rehash()` вернул `True` — пароль перехешируется без участия пользователя.

### JWT

**Access-токен** (15 мин):
- Stateless, не хранится в БД.
- Claims: `iss`, `sub`, `aud`, `exp`, `iat`, `nbf`, `jti`, `typ=access`, `amr`, `sid`.
- `amr` (authentication methods references) — для downstream-сервисов.

**Refresh-токен** (7 дней):
- Хранится в БД как HMAC-SHA256-хеш.
- Ротация: при использовании старый помечается `used=True`, выдаётся новый.
- **Replay detection**: повторное предъявление → все активные сессии пользователя инвалидируются.

**MFA-pending токен** (5 мин):
- `typ=mfa_pending`, даёт право только на `/auth/mfa/verify`.
- NIST SP 800-63B Rev 4 §5.2.2.

**OAuth** — `amr=["oauth"]` (RFC 8176). `require_mfa` (проверяет
`otp`/`webauthn`) не пропустит такого пользователя на критичные
операции без явного MFA-setup.

### MFA (TOTP)

- Секрет шифруется AES-256-GCM (или ГОСТ «Кузнечик»).
- AAD = `f"mfa:{user_id}"` — расшифровка чужого секрета невозможна.
- 10 backup-кодов (`XXXXX-XXXXX`, HMAC-SHA256, одноразовые).
- **Replay protection**: `last_used_totp_step` блокирует повторное использование одного TOTP-кода (§5.1.2).
- Rate limit: 5 попыток → 15 минут lockout, **изолирован** от `login`.

### OAuth2 (опционально)

- **Feature flag** `OAUTH_ENABLED=false` по умолчанию — для
  сертифицированного контура.
- CSRF-защита: подписанный state (HS256, TTL 5 мин).
- **Anti-enumeration**: не линкуем OAuth к существующему User по email.
- Токены возвращаются на frontend через URL **fragment** (`#`) —
  не уходят на сервер, не попадают в access-логи и Referer.
- Секреты провайдера (`client_secret`) — только в env, не в БД.
- Access/refresh провайдера **не хранятся** — работаем от имени
  пользователя один раз, забрали userinfo, забыли.

### Rate limiting

Счётчики изолированы по `scope`:

| Scope | Что | Лимит |
|---|---|---|
| `login` | `/auth/login` | 10 попыток → 5 мин |
| `mfa` | `/auth/mfa/verify`, `/users/me/mfa/*` | 5 попыток → 15 мин |
| `verify` | `/auth/verify-email` | 3/час |
| `reset` | `/auth/password-reset/request` | 3/час |
| `reset_interval` | `/auth/password-reset/request` | 1/60 сек |

Бэкенд: `memory` (dev, single-process) / `redis` (prod, multi-worker).

### Encryption

**AES-256-GCM** (fallback, несертифицированный контур):
- AEAD, nonce 12 байт, tag 16 байт.
- Ключ из `ENCRYPTION_KEY` (base64, 32 байта).

**ГОСТ «Кузнечик»** (сертифицированный контур):
- ГОСТ Р 34.12-2015, режим CFB (ГОСТ Р 34.13-2015).
- HMAC для целостности (в prod — HMAC-Стрибог).

**KeyProvider** — абстракция над источником мастер-ключа:
- `EnvKeyProvider` — читает `ENCRYPTION_KEY` из .env.
- `VaultKeyProvider` — заглушка; рецепт в `docs/EXTENSIONS.md`.

### Timing-safe

- **Login**: при отсутствии пользователя — verify dummy-хеша (Argon2 занимает ~50–100 ms, время ответа не отличается).
- **Password-reset**: для несуществующего email — `asyncio.sleep(0.05)` (защита от enumeration через тайминги).

### User enumeration

- Login: generic `Invalid email or password.`
- Register: generic `Email or username already registered.`
- Password reset: generic `If the provided information is correct...`
- Admin: 404 (не 403) для не-админов.
- OAuth: `#error=email_already_registered` (не раскрывает, что email
  у нас есть — общий код ошибки для «email занят» без разницы, чем).

### Audit

Все действия пишутся в `audit_logs` с JSONB-метаданными:
- `LOGIN_SUCCESS` / `LOGIN_FAILURE` / `LOGOUT`
- `USER_REGISTERED` / `USER_UPDATED`
- `PASSWORD_CHANGE` / `TOKEN_REFRESH` / `TOKEN_REVOKE`
- `ACCOUNT_LOCKED` / `ACCOUNT_UNLOCKED` / `MFA_ENABLED` / `MFA_DISABLED`
- `EMAIL_VERIFICATION_SENT` / `EMAIL_VERIFIED`
- `PASSWORD_RESET_REQUESTED` / `PASSWORD_RESET_COMPLETED`

С `user_id`, `success`, `correlation_id`, `ip_address`, `user_agent`, `metadata_json` (JSONB).

OAuth-события пишутся как `LOGIN_SUCCESS` с `metadata.method="oauth"`,
`metadata.provider="yandex"`.

---

## Разработка

### Пакетный менеджер — `uv`

| Операция | Команда |
|---|---|
| Установить зависимости | `uv sync` |
| Добавить зависимость | `uv add <pkg>` |
| Добавить dev-зависимость | `uv add --dev <pkg>` |
| Удалить зависимость | `uv remove <pkg>` |
| Обновить всё | `uv lock --upgrade` |
| Запустить команду | `uv run <cmd>` |
| Экспорт в requirements.txt | `uv export --format requirements-txt --no-dev -o requirements.txt` |

**Не активируй `.venv` вручную** — используй `uv run`.

### Запуск в dev

```bash
uv run uvicorn app.main:app --reload --log-config=-
```

`--log-config=-` отключает стандартный Uvicorn-лог (мы логируем сами через structlog).

### Линтеры

```bash
uv run ruff check app/
uv run ruff check --fix app/
uv run ruff format app/
uv run mypy app/
```

Конфигурация — в `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`).

### Makefile

Полный список: `make help`. Ключевые:

```bash
make check            # ruff + mypy + pytest
make dev              # uvicorn --reload
make infra-up         # postgres + redis в Docker
make migrate          # alembic upgrade head
make promote-admin e=admin@example.com
make smoke            # smoke-тест (после Фазы 5)
```

---

## Миграции

### Инициализация (один раз)

```bash
uv run alembic init migrations
```

Затем в `migrations/env.py` заменить настройку URL на чтение из `Settings`:

```python
from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

### Создание миграции

```bash
uv run alembic revision --autogenerate -m "add user table"
```

Проверить сгенерированный файл в `migrations/versions/` — Alembic не всегда правильно определяет изменения (особенно enum'ы, индексы, server_default).

### Применение

```bash
uv run alembic upgrade head          # до последней
uv run alembic upgrade +1            # на одну вперёд
uv run alembic downgrade -1          # откатить одну
uv run alembic history               # история
uv run alembic current               # текущая ревизия
```

### Правила

- **Никогда** не редактируй применённые миграции — создавай новую.
- **Всегда** проверяй `--autogenerate` вручную.
- Для enum-изменений (`ALTER TYPE ... ADD VALUE`) — пиши миграцию руками.
- В prod — миграции применяются через CI/CD.

---

## Тестирование

```bash
uv run pytest                          # все тесты
uv run pytest -v                       # verbose
uv run pytest tests/test_auth_flow.py  # один файл
uv run pytest -k "login"               # по имени
uv run pytest --cov=app --cov-report=html
```

### Структура тестов

```
tests/
├── conftest.py                  # фикстуры: app, client, db, user
├── test_health.py               # liveness/readiness
├── test_auth_flow.py            # happy-path: register → login → me → refresh → logout
├── test_auth_errors.py          # 401, 409, 422, replay detection
├── test_users.py                # профиль и сессии
├── test_mfa.py                  # MFA lifecycle + replay + lockout
├── test_email_verification.py   # verify-email flow
├── test_password_reset.py       # reset flow + quota + interval
├── test_rate_limit.py           # scope-изоляция, backoff, quota
├── test_admin.py                # admin endpoints + 404/403
├── test_metrics.py              # Prometheus /metrics
├── test_middleware.py           # graceful shutdown
├── test_keys.py                 # KeyProvider
├── test_oauth.py                # OAuth через mock YandexProvider
└── fuzz/                        # property-based (Hypothesis)
```

### Ключевые фикстуры

- **`client`** — `httpx.AsyncClient` с `ASGITransport`, override `get_db` и `get_email_sender`.
- **`db_session`** — сессия с SAVEPOINT, откатывается после теста.
- **`email_sender`** — `MockEmailSender`, собирает письма в `.sent`.
- **`reset_singletons`** (autouse) — сбрасывает `get_settings.cache_clear()`, rate limiter, JWT handler и т.п. перед каждым тестом.

---

## Структура проекта

```
fastapi-t/
├── app/
│   ├── __init__.py
│   ├── main.py                 # create_app(), lifespan, middleware
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # engine, session, Base, get_db
│   ├── models.py               # User, RefreshToken, AuditLog, MFADevice,
│   │                           #   EmailActionToken, OAuthAccount, GOSTKeyPair
│   ├── schemas.py              # Pydantic-схемы (request/response)
│   ├── exceptions.py           # RFC 9457 Problem Details
│   ├── dependencies.py         # get_current_user, require_mfa, require_admin
│   ├── middleware.py           # Correlation, ActiveRequests, RequestID (ASGI)
│   ├── logging_config.py       # structlog + contextvars
│   ├── audit.py                # write_audit (единая точка для audit_logs)
│   ├── metrics.py              # Prometheus Counter'ы и Gauge
│   ├── security/
│   │   ├── passwords.py        # Argon2id, HIBP
│   │   ├── encryption.py       # AES-GCM + ГОСТ Кузнечик
│   │   ├── jwt_handler.py      # JWT (HS256 / ES256 / GOST)
│   │   ├── jwks.py             # JWK / JWKS (ES256)
│   │   ├── keys.py             # KeyProvider: env / vault
│   │   ├── mfa.py              # TOTP + backup-коды
│   │   ├── tokens.py           # одноразовые action-токены
│   │   ├── rate_limit.py       # in-memory / Redis rate limiter
│   │   └── oauth/              # OAuth2-клиент (опционально)
│   │       ├── base.py         # OAuthProvider Protocol
│   │       ├── yandex.py       # YandexProvider
│   │       └── state.py        # подписанный state (CSRF)
│   ├── routers/
│   │   ├── health.py           # /health/live, /health/ready
│   │   ├── auth.py             # /auth/register, login, mfa/verify, refresh, logout
│   │   ├── users.py            # /users/me, sessions, password
│   │   ├── mfa.py              # /users/me/mfa/setup, verify, disable
│   │   ├── email.py            # /auth/verify-email, /auth/password-reset
│   │   ├── admin.py            # /admin/users/* (требует MFA)
│   │   └── oauth.py            # /auth/oauth/* (условно монтируется)
│   ├── scripts/
│   │   └── promote_admin.py    # CLI: сделать пользователя админом
│   └── services/
│       ├── email_sender.py     # SMTP / Mock
│       └── session.py          # persist_refresh_token (shared)
├── migrations/                 # Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 2026_09_24_2045_4613e3607c37_initial_schema.py
│       ├── 2026_10_01_1652_e50afcc51ddd_add_mfa_devices.py
│       ├── 2026_10_01_1733_9e2d917016d9_add_mfa_last_used_totp_step.py
│       ├── 2026_10_01_1749_889e318d15ce_add_email_action_tokens.py
│       ├── 2026_10_02_1200_a7b8c9d0e1f2_jsonb_audit_metadata.py
│       ├── 2026_10_02_1300_b8c9d0e1f2a3_add_is_admin.py
│       └── 2026_10_11_1200_c9d0e1f2a3b4_add_oauth_accounts.py
├── docker/
│   ├── postgres/init/          # init-скрипты PostgreSQL
│   └── postgres-exporter/      # queries.yaml для точных Gauge'ей
├── deploy/
│   ├── DEPLOY.md               # полная инструкция по деплою
│   ├── fastapi-t.service       # systemd unit
│   └── install.sh              # установщик
├── docs/
│   ├── API.md                  # полный API reference
│   ├── INTEGRATION.md          # интеграция в проекты
│   ├── ARCHITECTURE.md         # архитектурные решения
│   └── EXTENSIONS.md           # рецепты (OAuth, WebAuthn, JWKS…)
├── scripts/
│   ├── smoke-test.sh           # end-to-end smoke
│   └── load-test.js            # k6 load test
├── tests/
├── .env                        # локальные секреты (не коммитим)
├── .env.example                # шаблон
├── alembic.ini
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── CHANGELOG.md
├── Plan.md
├── Plan-OAuth.md
└── README.md
```

### Где что искать

| Задача | Файл |
|---|---|
| Добавить endpoint | `app/routers/<domain>.py` |
| Изменить поля User | `app/models.py` + миграция |
| Добавить request/response | `app/schemas.py` |
| Изменить политику пароля | `app/security/passwords.py` |
| Добавить claim в JWT | `app/security/jwt_handler.py` |
| Настроить rate limit | `app/security/rate_limit.py` + `app/config.py` |
| Добавить кастомную ошибку | `app/exceptions.py` |
| Изменить логирование | `app/logging_config.py` |
| Добавить middleware | `app/middleware.py` + `main.py` |
| Добавить метрику | `app/metrics.py` + инкремент в роутере |
| Создать админа | `make promote-admin e=...` |
| Добавить OAuth-провайдера | `app/security/oauth/<name>.py` + фабрика |
| Включить/выключить OAuth | `OAUTH_ENABLED` в `.env` |

---

## Соответствие стандартам

### NIST SP 800-63B Rev 4 (August 2025)

| Требование | Параграф | Реализация |
|---|---|---|
| Min 15 символов (single-factor) | §5.1.1.2 | `MIN_PASSWORD_LENGTH_SINGLE_FACTOR` |
| Min 8 символов (MFA) | §5.1.1.2 | `MIN_PASSWORD_LENGTH_MFA` |
| Max ≥ 64 символов | §5.1.1.2 | `MAX_PASSWORD_LENGTH` |
| **Нет** composition rules | §5.1.1.2 | Валидатор не проверяет регистр/цифры/спецсимволы |
| **Нет** периодической ротации | §5.1.1.2 | Отсутствует `password_expires_at` |
| Blocklist screening | §5.1.1.2 | HIBP Pwned Passwords (k-anonymity) |
| Recovery email SHALL be verified | §5.1.1.2 | `POST /auth/verify-email` + токен с TTL |
| Reset-токен одноразовый | §5.1.1.2 | `used_at` в `email_action_tokens` |
| Rate limiting на failed attempts | §5.2.2 | Scope `login` (10 → 5 мин), scope `mfa` (5 → 15 мин) |
| Rate limiting на email | §5.2.2 | Scope `verify`/`reset` (3/час), `reset_interval` (1/60 сек) |
| OTP SHALL NOT be accepted twice | §5.1.2 | `last_used_totp_step` в `mfa_devices` |
| MFA-челлендж изолирован | §5.2.2 | Отдельный `typ=mfa_pending` |
| Generic messages | §5.1.1.2 | Одинаковые ответы для enumeration |
| Session secrets non-persistent | §7.1 | Refresh в БД с TTL |
| Session SHALL NOT be extended | §7.2 | Ротация refresh + replay detection |
| `amr` claim | §4.2 | `User.auth_methods` → JWT `amr` |
| Federated identity | §4.2 | `amr=["oauth"]` (RFC 8176) для OAuth-login |

### ГОСТ / ФСБ / ФСТЭК

| Стандарт | Реализация |
|---|---|
| ГОСТ Р 34.10-2012 | `GOSTBackend` для JWT-подписи |
| ГОСТ Р 34.11-2012 (Стрибог) | Для HMAC в ГОСТ-контуре |
| ГОСТ Р 34.12-2015 (Кузнечик) | `GOSTKuznyechikCipher` |
| ГОСТ Р 34.13-2015 (CFB) | `encrypt_cfb` / `decrypt_cfb` |
| Приказ ФСБ № 378 (КС1-КС3) | `CryptoProfile.GOST` |
| Приказ ФСТЭК № 21 | Обоснование применения СКЗИ для ИСПДн |

**Для production в сертифицированном контуре** необходимы:
- КриптоПро CSP 5.0 или ViPNet CSP.
- HSM для хранения мастер-ключей.
- Оценка влияния среды функционирования (Приказ ФСБ № 524).
- **OAuth через публичных провайдеров — обычно запрещён.**
  `OAUTH_ENABLED=false` отключает модуль полностью (404, нет в OpenAPI).

### RFC

| RFC | Что реализует |
|---|---|
| RFC 6749 | OAuth 2.0 (authorization code flow) |
| RFC 7009 | OAuth 2.0 Token Revocation |
| RFC 7519 | JWT (claims, структура) |
| RFC 7638 | JWK Thumbprint (kid для ES256) |
| RFC 8176 | `amr` values (`oauth`, `otp`, `pwd`) |
| RFC 9457 | Problem Details for HTTP APIs |
| RFC 5321 | Формат email |
| RFC 6238 | TOTP |
| OWASP A07:2025 | Authentication Failures |

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'email_validator'`

```bash
uv add email-validator
```

### `ValidationError: jwt_secret_key Field required`

Нет `.env` или отсутствует `JWT_SECRET_KEY`:

```bash
cat .env | grep JWT_SECRET_KEY
openssl rand -hex 32
```

### `asyncpg.exceptions.InvalidPasswordError`

Проверь `POSTGRES_*` в `.env`:

```bash
docker compose ps
docker compose logs postgres
```

### `sqlalchemy.exc.MissingGreenlet`

Ленивая загрузка вне async-контекста. Решение: `expire_on_commit=False` (уже в `database.py`) + `selectinload()` для связей.

### Логи в prod не в JSON

Проверь `LOG_FORMAT=json` и `APP_ENV=prod`.

### `alembic.util.exc.CommandError: Target database is not up to date`

```bash
uv run alembic upgrade head
```

### `greenlet_spawn has not been called` в тестах

Используй `async_sessionmaker` с `expire_on_commit=False` и `AsyncClient` из `httpx`.

### `require_admin` возвращает 403 вместо 404

Это регрессия, если в `dependencies.py::require_admin` база — `MFAUser`.
Должно быть `CurrentUser` + порядок проверок `is_admin` → MFA.
См. `docs/ARCHITECTURE.md` → «`require_admin`: порядок проверок и 404».

### Pylance не видит модули

1. `Ctrl+Shift+P` → `Python: Select Interpreter` → `.venv/bin/python`.
2. Restart Language Server.

### `ImportError: cannot import name 'get_logger'`

Проверь `tail -20 app/logging_config.py` — там должна быть `def get_logger(...)`.

### `/metrics` возвращает 401/403

Проверь `METRICS_TOKEN` и заголовок `Authorization: Bearer <token>`.
См. `deploy/DEPLOY.md` → Troubleshooting.

### `/auth/oauth/*` возвращает 404

Проверь `OAUTH_ENABLED`. По умолчанию `false` — роутер не монтируется.
Включить: `OAUTH_ENABLED=true` + `OAUTH_YANDEX_CLIENT_ID`,
`OAUTH_YANDEX_CLIENT_SECRET`. Затем перезапустить сервис.

При `OAUTH_ENABLED=true` и отсутствии client_id/secret провайдер
неактивен — `/auth/oauth/providers` вернёт пустой список.

### OAuth callback → `#error=email_already_registered`

Email от Яндекса уже занят обычным пользователем. Это **намеренно**:
авто-линк по email = takeover через чужой OAuth-аккаунт.
Решение: пользователь должен сначала залогиниться паролем, потом
привязать OAuth через `/users/me/oauth/link` (не реализовано,
см. `docs/EXTENSIONS.md`).

### OAuth callback → `#error=invalid_state`

State подделан, истёк (>5 мин с момента `/authorize`) или пришёл
от другого провайдера. Проверь:
- `JWT_SECRET_KEY` совпадает на всех инстансах сервиса (state
  подписан им);
- между `/authorize` и `/callback` прошло < `OAUTH_STATE_TTL_SECONDS`;
- `provider_slug` в URL совпадает с тем, что был в `/authorize`.

### OAuth callback → `#error=token_exchange_failed`

Яндекс вернул 4xx на `/token`. Самые частые причины:
- `redirect_uri` в консоли Яндекса **не совпадает** с реальным
  (проверь byte-for-byte, включая trailing slash);
- `client_secret` устарел / перепутан с другим приложением;
- код `code` уже был обменян (можно использовать только один раз).

Логи: `yandex_token_exchange_failed` содержит status; `error=str(exc)`
в `yandex_token_request_failed` — сетевые проблемы.

---

## Лицензия

Proprietary. Все права защищены.