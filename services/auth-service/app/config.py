"""
Конфигурация приложения через pydantic-settings.

Источники (в порядке приоритета):
1. Аргументы Settings(...) — programmatic override
2. Environment variables — prod (K8s secrets, Docker env)
3. .env файл — локальная разработка
4. Дефолты в полях — fallback

Имена полей в lowercase → uppercase env-переменные:
    app_name  ←  APP_NAME
    jwt_secret_key  ←  JWT_SECRET_KEY
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Единая точка конфигурации.

    Обязательные поля (без дефолта) — fail-fast на старте:
    если чего-то нет, сервис не поднимется.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # игнорируем лишние env-переменные (docker-compose, CI)
    )

    # ═══════════════════════════════════════════════════════════════════════
    # App
    # ═══════════════════════════════════════════════════════════════════════
    app_name: str = "Auth Service"
    app_env: Literal["local", "dev", "stage", "prod"] = "local"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api/v1"
    app_version: str = "0.1.0"

    # ═══════════════════════════════════════════════════════════════════════
    # Logging
    # ═══════════════════════════════════════════════════════════════════════
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ═══════════════════════════════════════════════════════════════════════
    # Database (PostgreSQL)
    # ═══════════════════════════════════════════════════════════════════════
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "auth_user"
    postgres_password: str = "change_me"
    postgres_db: str = "auth_db"

    # Пул соединений (prod-тюнинг)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600  # 1 час
    db_echo: bool = False  # SQL-логирование (для отладки)

    # ═══════════════════════════════════════════════════════════════════════
    # Redis (distributed rate limiter, JWT blacklist, кэш)
    # ═══════════════════════════════════════════════════════════════════════
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_ssl: bool = False

    # ═══════════════════════════════════════════════════════════════════════
    # JWT
    # ═══════════════════════════════════════════════════════════════════════
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: Literal[
        "HS256",
        "HS512",
        "ES256",
        "ES512",
        "GOST3410-2012-256",
        "GOST3410-2012-512",
    ] = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_issuer: str = "auth-service"
    jwt_audience: str = "auth-service"

    # Публичный ключ (PEM) для JWKS. Нужен только для асимметричных
    # алгоритмов (ES256). Если не задан — деривируется из jwt_secret_key
    # (который в этом случае должен быть PEM-encoded EC private key).
    #
    # Для HS256/GOST не используется — JWKS отдаёт пустой массив.
    jwt_public_key: str | None = None

    # Key ID (kid) для JWT header. Связывает токен с конкретным
    # ключом в JWKS. Если не задан — RFC 7638 JWK Thumbprint публичного
    # ключа (SHA-256, стабилен между рестартами, меняется только при
    # ротации ключа).
    jwt_key_id: str | None = None



    # ═══════════════════════════════════════════════════════════════════════
    # MFA (TOTP)
    # ═══════════════════════════════════════════════════════════════════════
    # Issuer name, отображаемый в Google Authenticator / 1Password / Authy
    # при сканировании QR-кода.
    mfa_totp_issuer: str = "Auth Service"

    # TTL временного токена между "пароль верный" и "введи TOTP-код".
    # NIST SP 800-63B Rev 4 §5.2.2: короткое окно для второй ступени.
    mfa_temp_token_expire_seconds: int = 300  # 5 минут

    # Количество backup-кодов, выдаваемых при включении MFA.
    mfa_backup_codes_count: int = 10

    # Окно допустимого расхождения часов при проверке TOTP.
    # 1 = ±30 секунд (итого окно 90 сек). 0 — только текущий шаг.
    mfa_totp_valid_window: int = 1

    # ═══════════════════════════════════════════════════════════════════════
    # OAuth2 (внешние identity providers)
    # ═══════════════════════════════════════════════════════════════════════
    #
    # ВАЖНО для защищённого контура (ГОСТ/ФСБ):
    # OAuth через публичных провайдеров (Яндекс, Google, ...) обычно
    # ЗАПРЕЩЁН — пользователь должен аутентифицироваться только через
    # локальные credentials, а внешний IdP не входит в границу доверия.
    #
    # Флаг `oauth_enabled=False` (default) полностью отключает модуль:
    # роутер не монтируется в FastAPI, эндпоинты /auth/oauth/* дают 404,
    # их нет в OpenAPI. Это правильнее, чем "монтируется, но возвращает
    # 503": не раскрываем факт наличия функциональности.
    oauth_enabled: bool = False

    # ── Яндекс ID ─────────────────────────────────────────────────────────
    # Регистрация приложения: https://oauth.yandex.ru/client/new
    # Redirect URI (указывается в консоли провайдера, должен совпадать
    # byte-for-byte): {oauth_public_base_url}/api/v1/auth/oauth/yandex/callback
    #
    # Оба поля пустые (None) → провайдер неактивен даже при
    # oauth_enabled=True. Это позволяет включать флаг заранее, до
    # получения credentials.
    oauth_yandex_client_id: str | None = None
    oauth_yandex_client_secret: str | None = None

    # TTL подписанного state-токена (CSRF-защита OAuth-flow).
    # 5 минут — с запасом на ввод credentials у провайдера.
    oauth_state_ttl_seconds: int = 300

    # Публичный базовый URL сервиса — для сборки redirect_uri.
    # В prod: https://auth.example.com (без trailing slash).
    oauth_public_base_url: str = "http://localhost:8000"

    # Куда редиректить после callback. Токены передаются в URL fragment
    # (#access_token=...), а не в query — fragment не уходит на сервер
    # и не попадает в access-логи reverse-proxy / Referer.
    oauth_frontend_callback_url: str = "http://localhost:3000/oauth/callback"

    # ═══════════════════════════════════════════════════════════════════════
    # Encryption (AES-256-GCM / ГОСТ Кузнечик)
    # ═══════════════════════════════════════════════════════════════════════
    # 32 байта в base64. Генерация: openssl rand -base64 32
    encryption_key: str = Field(..., description="base64-encoded 32-byte key")

    # ── Источник мастер-ключа ─────────────────────────────────────────────
    # "env"   — ENCRYPTION_KEY из .env / env-переменных (default).
    # "vault" — HashiCorp Vault. Требует VAULT_ADDR + VAULT_TOKEN.
    #           Заглушка (VaultKeyProvider бросает NotImplementedError) —
    #           реализация описана в docs/EXTENSIONS.md.
    key_provider: Literal["env", "vault"] = "env"

    # Адрес Vault (например, "http://vault:8200"). Используется
    # только если key_provider="vault". Не валидируется на старте —
    # VaultKeyProvider недоступен, пока его не реализуют.
    vault_addr: str | None = None

    # Токен доступа к Vault (AppRole / Kubernetes SA / root token
    # для dev). Используется только если key_provider="vault".
    vault_token: str | None = None

    # ═══════════════════════════════════════════════════════════════════════
    # Rate limiting
    # ═══════════════════════════════════════════════════════════════════════
    # ── Общие (lockout с экспоненциальным backoff, scope="login") ──────────
    rate_limit_max_attempts: int = 10
    rate_limit_lockout_seconds: int = 300  # 5 минут
    # TTL для записей в Redis (в секундах).
    # Если lockout превышает TTL — запись истечёт раньше блокировки.
    # Поэтому TTL должен быть >= максимального lockout.
    rate_limit_redis_ttl: int = 900  # 15 минут

    # Хранилище счётчиков:
    # - "memory" — in-memory (dev, single-process). Не работает при > 1 воркере.
    # - "redis"  — distributed (prod, multi-worker / multi-instance).
    rate_limit_backend: Literal["memory", "redis"] = "memory"

    # Hard cap на экспоненциальный backoff.
    # NIST SP 800-63B Rev 4 §5.2.2: "SHALL NOT lockout for more than
    # 100 failed attempts." Мы используем backoff base * 2^(violations-1),
    # который без cap'а растёт бесконечно. Cap = 24 часа — потолок,
    # дальше держим постоянным.
    rate_limit_max_lockout_seconds: int = 86400  # 24 часа

    # ── MFA (scope="mfa") ──────────────────────────────────────────────────
    # NIST SP 800-63B Rev 4 §5.2.2: rate limiting на failed attempts.
    # TOTP-код — 6 цифр (10^6 комбинаций). При 5 попытках и lockout
    # 15 минут brute-force практически невозможен.
    rate_limit_mfa_verify_max_attempts: int = 5
    rate_limit_mfa_verify_lockout_seconds: int = 900  # 15 минут

    # ── Email endpoints (quota, scope="verify" / "reset") ──────────────────
    # NIST §5.1.1.2 + OWASP A07:2025: ограничение частоты запросов писем
    # (защита от email-bombing и abuse отправки).
    # Применяется к:
    #   - POST /auth/verify-email
    #   - POST /auth/password-reset/request
    rate_limit_email_per_hour: int = 3

    # Минимальный интервал между двумя письмами сброса пароля.
    # Защита от «нажал 10 раз подряд → пришло 10 писем».
    # Не раскрывает существование email: ответ всегда generic 200,
    # письмо просто не отправляется (OWASP A07:2025).
    rate_limit_password_reset_min_interval_seconds: int = 60

    # ═══════════════════════════════════════════════════════════════════════
    # Breach check (HIBP)
    # ═══════════════════════════════════════════════════════════════════════
    hibp_enabled: bool = True
    hibp_timeout_seconds: float = 5.0
    hibp_fail_open: bool = True  # при недоступности HIBP — пропускать

    # ═══════════════════════════════════════════════════════════════════════
    # CORS
    # ═══════════════════════════════════════════════════════════════════════
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_allow_credentials: bool = True
    cors_max_age: int = 600

    # ═══════════════════════════════════════════════════════════════════════
    # Trusted hosts (prod)
    # ═══════════════════════════════════════════════════════════════════════
    trusted_hosts: list[str] = ["*"]

    # ═══════════════════════════════════════════════════════════════════════
    # OpenAPI / Docs
    # ═══════════════════════════════════════════════════════════════════════
    openapi_docs_enabled: bool = True  # в prod — отключаем в main.py

    # ═══════════════════════════════════════════════════════════════════════
    # Metrics (Prometheus)
    # ═══════════════════════════════════════════════════════════════════════
    # Включать /metrics endpoint. В prod — обычно True, но защищать
    # через metrics_require_auth (см. ниже) или отдельный порт.
    metrics_enabled: bool = True

    # Требовать Bearer-токен для /metrics.
    # В prod — True: /metrics может раскрывать внутреннюю топологию
    # (endpoint'ы, коды ошибок, latency). Prometheus scrape-конфиг
    # должен передавать Authorization header.
    metrics_require_auth: bool = False

    # Токен для доступа к /metrics (если metrics_require_auth=True).
    # В prod — из K8s secret, не из .env. Сгенерировать: openssl rand -hex 32
    metrics_token: str | None = None

    # ═══════════════════════════════════════════════════════════════════════
    # Frontend (для сборки ссылок в письмах)
    # ═══════════════════════════════════════════════════════════════════════
    frontend_url: str = "http://localhost:3000"

    # ═══════════════════════════════════════════════════════════════════════
    # Email: верификация и сброс пароля
    # ═══════════════════════════════════════════════════════════════════════
    email_verification_token_ttl_seconds: int = 86400   # 24 часа
    password_reset_token_ttl_seconds: int = 3600        # 1 час

    # ═══════════════════════════════════════════════════════════════════════
    # SMTP (пусто = no-op, письма только логируются)
    # ═══════════════════════════════════════════════════════════════════════
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_start_tls: bool = True
    smtp_timeout_seconds: float = 10.0
    email_from: str = "noreply@localhost"

    # ═══════════════════════════════════════════════════════════════════════
    # pgAdmin (только для dev, не читается приложением)
    # ═══════════════════════════════════════════════════════════════════════
    pgadmin_email: str = "admin@local.dev"
    pgadmin_password: str = "admin"
    pgadmin_port: int = 5050

    # ═══════════════════════════════════════════════════════════════════════
    # Computed fields
    # ═══════════════════════════════════════════════════════════════════════

    @computed_field
    @property
    def database_url(self) -> str:
        """
        Async DSN для SQLAlchemy (asyncpg).

        Формат: postgresql+asyncpg://user:pass@host:port/db
        """
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field
    @property
    def database_url_sync(self) -> str:
        """
        Синхронный DSN (psycopg2).

        Нужен для:
        - Alembic offline-режима
        - Утилит (pg_dump, backup)
        """
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        """
        DSN для Redis.

        Формат: redis://[:password@]host:port/db
        """
        scheme = "rediss" if self.redis_ssl else "redis"
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"{scheme}://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @computed_field
    @property
    def is_production(self) -> bool:
        """True, если app_env == 'prod'."""
        return self.app_env == "prod"

    @computed_field
    @property
    def is_development(self) -> bool:
        """True, если app_env в ('local', 'dev')."""
        return self.app_env in ("local", "dev")

    @computed_field
    @property
    def docs_enabled(self) -> bool:
        """
        Включены ли /docs, /redoc, /openapi.json.

        В prod отключены (защита от enumeration), но можно
        переопределить через OPENAPI_DOCS_ENABLED=true.
        """
        if self.is_production:
            return self.openapi_docs_enabled
        return True


@lru_cache
def get_settings() -> Settings:
    """
    Singleton-обёртка: конфиг читается один раз за жизнь процесса.

    lru_cache гарантирует, что Settings() создаётся один раз, а не
    при каждом импорте/запросе. В тестах можно сбросить через
    get_settings.cache_clear().
    """
    return Settings()
