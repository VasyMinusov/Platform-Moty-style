"""
Pytest-фикстуры для интеграционных тестов.

Стратегия:
- Отдельная тестовая БД (auth_test) — не задевает dev-данные.
- HIBP отключён (иначе тесты ходят в сеть и тормозят).
- Каждый тест — в своей транзакции (SAVEPOINT), откатывается после.
- Singleton'ы (jwt, encryption, rate limiter) сбрасываются между тестами.

Env-переменные задаются ДО импорта app.*, чтобы Settings() увидел их.
"""

import asyncio
import base64
import os

# ─── Env для тестов (ДО импорта app) ───────────────────────────────────────
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("POSTGRES_DB", "auth_test")
os.environ.setdefault("HIBP_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_BACKEND", "memory")
# OAuth включён в тестах по умолчанию. Тест «oauth_enabled=False → 404»
# создаёт отдельный app (см. test_oauth.py::test_oauth_disabled_returns_404).
#
# Провайдер яндекса «сконфигурирован» fake-кредами — реальные HTTP-запросы
# к Яндексу никогда не идут: тесты патчат YandexProvider.exchange_code /
# fetch_user_info через monkeypatch.
os.environ.setdefault("OAUTH_ENABLED", "true")
os.environ.setdefault("OAUTH_YANDEX_CLIENT_ID", "test-client-id")
os.environ.setdefault("OAUTH_YANDEX_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OAUTH_PUBLIC_BASE_URL", "http://test")
os.environ.setdefault(
    "OAUTH_FRONTEND_CALLBACK_URL",
    "http://frontend.test/oauth/callback",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-min-32-chars-long-0123456789abcdef",
)
# 32 байта в base64. Оригинальная строка (для теста test_env_key_provider_decodes_base64):
#     b"test-encryption-key-32-bytes-len"  — ровно 32 байта.
# Проверка: python -c 'import base64; print(len(base64.b64decode("...")), base64.b64decode("..."))'
os.environ.setdefault(
    "ENCRYPTION_KEY",
    base64.b64encode(b"test-encryption-key-32-bytes-len").decode(),
)

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

# Импорты приложения — только после установки env
from app.config import get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security.encryption import reset_encryption_service  # noqa: E402
from app.security.jwt_handler import reset_jwt_handler  # noqa: E402
from app.security.keys import reset_key_provider  # noqa: E402
from app.security.passwords import (  # noqa: E402
    reset_breach_checker,
    reset_password_hasher,
)
from app.security.rate_limit import (  # noqa: E402
    init_rate_limiter,
    reset_rate_limiter,
)

from app.services.email_sender import (  # noqa: E402
    get_email_sender,
)


# ═══════════════════════════════════════════════════════════════════════════
# MockEmailSender
# ═══════════════════════════════════════════════════════════════════════════


class MockEmailSender:
    """
    Заменяет EmailSender в тестах.

    Не отправляет письма. Собирает вызовы в `sent` — тесты читают
    оттуда `context["action_url"]` и извлекают токен.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text_template: str,
        html_template: str,
        context: dict,
    ) -> None:
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "text_template": text_template,
                "html_template": html_template,
                "context": context,
            }
        )

    def last_url(self) -> str:
        """URL последнего письма (action_url)."""
        if not self.sent:
            raise AssertionError("No emails sent")
        url = self.sent[-1]["context"].get("action_url")
        if not isinstance(url, str):
            raise AssertionError("No action_url in email context")
        return url

    def last_token(self) -> str:
        """Извлечь токен из URL последнего письма (?token=...)."""
        from urllib.parse import parse_qs, urlparse

        url = self.last_url()
        qs = parse_qs(urlparse(url).query)
        tokens = qs.get("token")
        if not tokens:
            raise AssertionError(f"No token in URL: {url}")
        return tokens[0]


# ═══════════════════════════════════════════════════════════════════════════
# URL-ы
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """DSN тестовой БД (auth_test)."""
    s = get_settings()
    return (
        f"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/auth_test"
    )


@pytest.fixture(scope="session")
def admin_db_url() -> str:
    """DSN служебной БД postgres — для создания auth_test, если её нет."""
    s = get_settings()
    return (
        f"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/postgres"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Схема (создаётся один раз на сессию)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def ensure_test_schema(test_db_url: str, admin_db_url: str) -> None:
    """
    Гарантирует, что auth_test существует и схема создана.

    Создание БД — через служебную postgres (idempotent).
    Схема — drop_all + create_all (изолированно).

    Использует asyncio.run() в sync-фикстуре: это позволяет
    один раз настроить БД в session scope, не возясь с loop_scope.
    """

    async def _setup() -> None:
        # 1. Создаём auth_test, если нет
        admin_engine = create_async_engine(admin_db_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'auth_test'")
            )
            if result.scalar_one_or_none() is None:
                await conn.execute(text("CREATE DATABASE auth_test OWNER auth_user"))
        await admin_engine.dispose()

        # 2. Создаём схему
        engine = create_async_engine(test_db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())


# ═══════════════════════════════════════════════════════════════════════════
# DB-сессия (function scope, откатывается после теста)
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db_session(
    ensure_test_schema: None,
    test_db_url: str,
) -> AsyncGenerator[AsyncSession]:
    """
    Async-сессия с SAVEPOINT, откатывается после теста.

    Все коммиты (`await session.commit()` в override_get_db) уходят
    в SAVEPOINT и не сохраняются между тестами.

    NullPool — чтобы соединение закрывалось сразу (не пул).

    join_transaction_mode="create_savepoint" — режим, при котором
    вызовы commit()/rollback() внутри сессии работают как
    RELEASE/ROLLBACK SAVEPOINT, не закрывая родительскую транзакцию.
    Это позволяет откатить весь тест через `await transaction.rollback()`.
    """
    engine: AsyncEngine = create_async_engine(test_db_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()

    factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    async with factory() as session:
        yield session

    await transaction.rollback()
    await connection.close()
    await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# Mock email sender
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def email_sender() -> MockEmailSender:
    """Свежий mock на каждый тест."""
    return MockEmailSender()


# ═══════════════════════════════════════════════════════════════════════════
# HTTP-клиент
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    email_sender: MockEmailSender,
) -> AsyncGenerator[AsyncClient]:
    """
    Async HTTP-клиент с override get_db и get_email_sender.

    Все запросы идут в тестовую БД через ASGITransport (без реальной сети).
    Письма не отправляются в SMTP, а собираются в mock (см. фикстуру
    email_sender — тесты читают оттуда action_url и токен).

    ВАЖНО: override_get_db повторяет транзакционную семантику реального
    get_db (app/database.py): commit() при успехе, rollback() при исключении.
    """
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: email_sender

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Сброс singleton'ов
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
async def reset_singletons() -> AsyncGenerator[None]:
    """
    Сбрасывает singleton'ы перед каждым тестом.

    Иначе rate limiter, jwt handler и т.п. сохранят состояние между тестами.

    ВАЖНО: get_settings.cache_clear() здесь критичен.
    lru_cache держит Settings на уровне процесса. Тесты, которые
    делают monkeypatch.setenv + get_settings.cache_clear() (например,
    tests/test_keys.py), откатывают env после теста, но кэш остаётся
    с прошлыми значениями — следующий тест получит устаревший Settings.
    Без этого сброса видим каскадные ошибки вроде "ENCRYPTION_KEY must
    decode to 32 bytes, got 16" или "VaultKeyProvider не реализован".

    Async, потому что init_rate_limiter() — асинхронный (в Redis-режиме
    делает PING). В тестах backend=memory, так что init мгновенный.
    """
    # Settings — до всех singleton'ов, которые от него зависят.
    get_settings.cache_clear()

    reset_jwt_handler()
    reset_encryption_service()
    reset_key_provider()
    reset_breach_checker()
    reset_password_hasher()
    reset_rate_limiter()

    # Rate limiter должен быть инициализирован до первого запроса.
    # В проде это делает lifespan; в тестах приложение создаётся без
    # запуска lifespan (ASGITransport не триггерит startup), поэтому
    # инициализируем вручную.
    await init_rate_limiter()

    yield

    # После теста — сбросить, чтобы следующий получил свежий limiter.
    reset_rate_limiter()


# ═══════════════════════════════════════════════════════════════════════════
# Helpers для тестов
# ═══════════════════════════════════════════════════════════════════════════


async def reset_and_reinit_rate_limiter() -> None:
    """
    Полный сброс rate limiter (все scope, все счётчики).

    Используется в тестах, которым нужно обойти ВСЕ ограничения
    (например, при проверке инвалидации старых токенов, где два
    запроса идут подряд — а prod-код намеренно throttle'ит второй).

    Не требует HTTP-контекста — работает напрямую с singleton'ом.
    """
    from app.security.rate_limit import init_rate_limiter, reset_rate_limiter

    reset_rate_limiter()
    await init_rate_limiter()


async def clear_reset_interval_quota(email: str = "reset@example.com") -> None:
    """
    Сбросить ТОЛЬКО min-interval для password-reset (scope="reset_interval").

    Используется в тестах, которым нужно сделать несколько подряд
    запросов password-reset (например, чтобы проверить инвалидацию
    старого токена). В prod-логике это соответствует «подождать
    60 секунд между запросами».

    ВАЖНО: не трогает hourly-quota (scope="reset") — она накапливается
    как в prod, что позволяет тестировать «4-й запрос → 429».
    """
    from app.security.rate_limit import get_rate_limiter

    limiter = get_rate_limiter()
    await limiter.clear_quota("reset_interval", email.lower())