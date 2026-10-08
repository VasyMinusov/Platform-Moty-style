from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://ctf:ctf@localhost:5432/ctf"
    jwt_secret: str = "dev_secret_change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    challenges_dir: str = "/challenges"
    # Подпапка внутри challenges_dir, куда распаковываются задания соревнований.
    # Итоговый путь: {challenges_dir}/{competitions_subdir}/{comp_slug}/{ch_slug}
    competitions_subdir: str = "competitions"

    challenge_port_range_start: int = 30000
    challenge_port_range_end: int = 30999
    instance_ttl_seconds: int = 3600

    docker_network: str = "ctf-platform_isolated_net"

    public_host: str = "localhost"

    # Лимиты ZIP-загрузки задания соревнования.
    competition_zip_max_bytes: int = 500 * 1024 * 1024
    competition_zip_max_files: int = 5000

    class Config:
        env_file = ".env"


settings = Settings()