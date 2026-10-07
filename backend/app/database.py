from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

# pool_size + max_overflow = максимум одновременных соединений.
# 20 + 40 = 60 — с запасом для 10–15 параллельных пользователей,
# но всё ещё ниже дефолтного max_connections=100 в PostgreSQL.
# pool_recycle переоткрывает соединения старше 30 минут: спасает от
# "server closed the connection unexpectedly" после рестарта БД.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()