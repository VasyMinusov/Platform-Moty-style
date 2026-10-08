from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://ctf:ctf@localhost:5432/ctf"
    jwt_secret: str = "dev_secret_change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    challenges_dir: str = "/challenges"
    competitions_subdir: str = "competitions"

    challenge_port_range_start: int = 30000
    challenge_port_range_end: int = 30999
    instance_ttl_seconds: int = 3600

    docker_network: str = "ctf-platform_isolated_net"

    public_host: str = "localhost"

    # Лимиты ZIP-загрузки задания соревнования.
    competition_zip_max_bytes: int = 500 * 1024 * 1024
    competition_zip_max_files: int = 5000

    # Rate limiting.
    rate_limit_enabled: bool = True

    # Hardening сборки.
    # Разрешать только базовые образы из allowlist.
    build_enforce_base_image_allowlist: bool = True
    # Сборка без сети.
    build_no_network: bool = True
    # Таймаут сборки в секундах.
    build_timeout_seconds: int = 900
    # Лимиты ресурсов на этап сборки.
    build_mem_limit: str = "2g"
    build_cpu_quota: int = 100_000  # 1 CPU

    class Config:
        env_file = ".env"


settings = Settings()