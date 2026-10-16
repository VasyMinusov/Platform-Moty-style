from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database (CTF-platform) ──────────────────────────────────
    database_url: str = "postgresql+psycopg2://ctf:ctf@localhost:5432/ctf"

    # ── Auth-service integration ─────────────────────────────────
    # JWT-секрет ОБЩИЙ с auth-service (HS256). Используется ТОЛЬКО
    # для валидации access-токенов, приходящих от auth-service.
    # Генерация токенов теперь целиком на стороне auth-service.
    auth_jwt_secret: str = "dev_secret_change_me"
    auth_jwt_algorithm: str = "HS256"
    auth_issuer: str = "auth-service"
    auth_audience: str = "auth-service"

    # URL для server-to-server вызовов (lazy provisioning,
    # bootstrap admin/moderator). Внутри docker-сети — имя сервиса.
    auth_service_url: str = "http://auth-service:8000"

    # ── Bootstrap: первые пользователи ───────────────────────────
    #
    # ВАЖНО про домен .internal:
    # Pydantic EmailStr в auth-service отвергает .localhost и другие
    # special-use домены (RFC 6761). .internal — безопасная замена.
    #
    # Пароли должны удовлетворять NIST-политике auth-service:
    #   - минимум 15 символов для single-factor;
    #   - не содержать username/email;
    #   - не быть в HIBP breach list.
    admin_username: str = "VasyMinusov"
    admin_email: str = "admin@ctf-platform.internal"
    admin_password: str = "0907Seva!!!2003"

    moderator_username: str = "moderator"
    moderator_email: str = "moderator@ctf-platform.internal"
    moderator_password: str = "moderato1234567"

    # ── Challenges / instances ───────────────────────────────────
    challenges_dir: str = "/challenges"
    competitions_subdir: str = "competitions"

    challenge_port_range_start: int = 30000
    challenge_port_range_end: int = 30999
    instance_ttl_seconds: int = 3600

    docker_network: str = "ctf-platform_isolated_net"

    public_host: str = "localhost"

    # ── ZIP-загрузка заданий соревнований ────────────────────────
    competition_zip_max_bytes: int = 500 * 1024 * 1024
    competition_zip_max_files: int = 5000

    # ── Rate limiting (глобальный, для CTF-специфичных эндпоинтов)─
    rate_limit_enabled: bool = True

    # ── Hardening сборки ─────────────────────────────────────────
    build_enforce_base_image_allowlist: bool = True
    build_no_network: bool = False
    build_timeout_seconds: int = 900
    build_mem_limit: str = "2g"
    build_cpu_quota: int = 100_000  # 1 CPU

    class Config:
        env_file = ".env"


settings = Settings()