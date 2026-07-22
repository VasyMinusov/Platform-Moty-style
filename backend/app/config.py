from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://ctf:ctf@localhost:5432/ctf"
    jwt_secret: str = "dev_secret_change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    challenges_dir: str = "/challenges"
    challenge_port_range_start: int = 30000
    challenge_port_range_end: int = 30999
    instance_ttl_seconds: int = 3600

    docker_network: str = "ctf-platform_isolated_net"

    # Хост, по которому пользователи достучатся до опубликованного порта
    # инстанса задания (см. routers/challenges.py -> start_challenge).
    # Раньше это было захардкожено как "host.ctf.example" — ссылка была
    # нерабочей "из коробки". Для локального запуска оставьте localhost,
    # для сервера — укажите его публичный домен/IP через переменную
    # окружения PUBLIC_HOST.
    public_host: str = "localhost"

    class Config:
        env_file = ".env"


settings = Settings()