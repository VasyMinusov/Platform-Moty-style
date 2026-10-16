"""
Тесты OAuth2 через Яндекс.

Провайдер мокается через monkeypatch на методы YandexProvider:
- exchange_code → возвращает OAuthTokens без HTTP-запроса
- fetch_user_info → возвращает OAuthUserInfo без HTTP-запроса

Это позволяет тестировать реальный роутер + YandexProvider (валидация
is_configured, build_authorize_url) без сети.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.main import create_app
from app.models import OAuthAccount, User
from app.security.oauth.base import (
    OAuthProviderError,
    OAuthTokens,
    OAuthUserInfo,
)
from app.security.oauth.yandex import YandexProvider
from app.services.email_sender import get_email_sender

VALID_PASSWORD = "correct horse battery staple nist"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _extract_state(authorize_url: str) -> str:
    """Достать state из URL, на который редиректит /authorize."""
    qs = parse_qs(urlparse(authorize_url).query)
    states = qs.get("state")
    assert states, f"no state in {authorize_url}"
    return states[0]


def _patch_yandex(
    monkeypatch: pytest.MonkeyPatch,
    *,
    userinfo: OAuthUserInfo,
    exchange_error: OAuthProviderError | None = None,
) -> None:
    """Смокать HTTP-обмен у YandexProvider."""

    async def fake_exchange(self, *, code: str, redirect_uri: str) -> OAuthTokens:
        if exchange_error is not None:
            raise exchange_error
        assert code, "code must be non-empty"
        assert redirect_uri, "redirect_uri must be non-empty"
        return OAuthTokens(access_token="fake-yandex-token", expires_in=3600)

    async def fake_userinfo(self, tokens: OAuthTokens) -> OAuthUserInfo:
        return userinfo

    monkeypatch.setattr(YandexProvider, "exchange_code", fake_exchange)
    monkeypatch.setattr(YandexProvider, "fetch_user_info", fake_userinfo)


async def _do_authorize(client: AsyncClient) -> str:
    """
    Запустить /authorize, вернуть state.
    follow_redirects=False, иначе httpx пойдёт на oauth.yandex.ru.
    """
    r = await client.get(
        "/api/v1/auth/oauth/yandex/authorize",
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return _extract_state(r.headers["location"])


# ═══════════════════════════════════════════════════════════════════════════
# /providers
# ═══════════════════════════════════════════════════════════════════════════


async def test_providers_list_includes_yandex(client: AsyncClient) -> None:
    """При oauth_enabled=true и заданных кредах — yandex в списке."""
    r = await client.get("/api/v1/auth/oauth/providers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    slugs = {p["slug"] for p in body}
    assert "yandex" in slugs

    yandex = next(p for p in body if p["slug"] == "yandex")
    assert yandex["display_name"] == "Яндекс ID"
    # Секретов не отдаём
    assert "client_id" not in yandex
    assert "client_secret" not in yandex


# ═══════════════════════════════════════════════════════════════════════════
# /authorize
# ═══════════════════════════════════════════════════════════════════════════


async def test_authorize_redirects_to_yandex(client: AsyncClient) -> None:
    """302 на oauth.yandex.ru с client_id, redirect_uri, state."""
    r = await client.get(
        "/api/v1/auth/oauth/yandex/authorize",
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith("https://oauth.yandex.ru/authorize?")

    qs = parse_qs(urlparse(location).query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["response_type"] == ["code"]
    assert qs["state"]
    # redirect_uri — наш callback (base_url в тестах: http://test)
    assert qs["redirect_uri"] == [
        "http://test/api/v1/auth/oauth/yandex/callback"
    ]


async def test_authorize_unknown_provider_returns_404(client: AsyncClient) -> None:
    """Неизвестный slug → 404."""
    r = await client.get(
        "/api/v1/auth/oauth/unknown-provider/authorize",
        follow_redirects=False,
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# /callback — happy path
# ═══════════════════════════════════════════════════════════════════════════


async def test_callback_creates_new_user_and_returns_tokens(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """
    Полный flow: authorize → callback → 302 на frontend с токенами.
    Новый User создан, OAuthAccount создан.
    """
    userinfo = OAuthUserInfo(
        provider_user_id="12345678",
        email="new-oauth@example.com",
        email_verified=True,
        username="newoauth",
        full_name="New OAuth",
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    state = await _do_authorize(client)

    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "authcode", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith("http://frontend.test/oauth/callback#")

    fragment = parse_qs(urlparse(location).fragment)
    assert "access_token" in fragment
    assert "refresh_token" in fragment
    assert "session_id" in fragment
    assert fragment["token_type"] == ["Bearer"]

    # User создан
    user_row = await db_session.execute(
        select(User).where(User.email == "new-oauth@example.com")
    )
    user = user_row.scalar_one()
    assert user.is_email_verified is True
    assert user.status.value == "active"
    assert user.auth_methods == "oauth"
    assert user.is_mfa_enabled is False  # MFA не выставляется автоматически

    # OAuthAccount создан
    acc_row = await db_session.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == user.id)
    )
    account = acc_row.scalar_one()
    assert account.provider == "yandex"
    assert account.provider_user_id == "12345678"
    assert account.provider_email == "new-oauth@example.com"


async def test_callback_existing_account_reuses_user(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """Второй callback с тем же provider_user_id — тот же User, без дублирования."""
    userinfo = OAuthUserInfo(
        provider_user_id="99999999",
        email="reuse@example.com",
        email_verified=True,
        username="reuse",
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    # 1-й callback — создаёт
    state1 = await _do_authorize(client)
    r1 = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c1", "state": state1},
        follow_redirects=False,
    )
    assert r1.status_code == 302

    # 2-й callback — находит существующего
    state2 = await _do_authorize(client)
    r2 = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c2", "state": state2},
        follow_redirects=False,
    )
    assert r2.status_code == 302

    # Ровно один User с этим email
    users = (
        await db_session.execute(select(User).where(User.email == "reuse@example.com"))
    ).scalars().all()
    assert len(users) == 1

    # Ровно один OAuthAccount
    accounts = (
        await db_session.execute(
            select(OAuthAccount).where(OAuthAccount.provider_user_id == "99999999")
        )
    ).scalars().all()
    assert len(accounts) == 1


# ═══════════════════════════════════════════════════════════════════════════
# /callback — ошибки
# ═══════════════════════════════════════════════════════════════════════════


async def test_callback_email_already_registered(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Email занят обычным пользователем → error=email_already_registered.
    Q2=(a): не линкуем автоматически.
    """
    # Существующий пользователь через обычную регистрацию
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "taken@example.com",
            "username": "takenuser",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201

    userinfo = OAuthUserInfo(
        provider_user_id="11111111",
        email="taken@example.com",
        email_verified=True,
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    state = await _do_authorize(client)
    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    fragment = parse_qs(urlparse(r.headers["location"]).fragment)
    assert fragment["error"] == ["email_already_registered"]


async def test_callback_invalid_state(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подделанный state → error=invalid_state."""
    userinfo = OAuthUserInfo(
        provider_user_id="1",
        email="x@example.com",
        email_verified=True,
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c", "state": "not.a.jwt"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    fragment = parse_qs(urlparse(r.headers["location"]).fragment)
    assert fragment["error"] == ["invalid_state"]


async def test_callback_state_wrong_provider(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    State с другим провайдером → invalid_state.

    Проверяем cross-provider защиту: state для yandex не примется
    в callback google (если бы google был).
    """
    # Подписываем state с provider="google", предъявляем в yandex.
    from app.security.oauth.state import sign_state

    google_state = sign_state(provider="google")

    userinfo = OAuthUserInfo(
        provider_user_id="1",
        email="x@example.com",
        email_verified=True,
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c", "state": google_state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    fragment = parse_qs(urlparse(r.headers["location"]).fragment)
    assert fragment["error"] == ["invalid_state"]


async def test_callback_provider_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Провайдер упал на обмене code → error=<reason>."""
    _patch_yandex(
        monkeypatch,
        userinfo=OAuthUserInfo(
            provider_user_id="1", email="x@example.com", email_verified=True
        ),
        exchange_error=OAuthProviderError("token_exchange_failed"),
    )

    state = await _do_authorize(client)
    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "bad", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    fragment = parse_qs(urlparse(r.headers["location"]).fragment)
    assert fragment["error"] == ["token_exchange_failed"]


async def test_callback_email_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Провайдер не вернул email → error=email_missing."""
    userinfo = OAuthUserInfo(
        provider_user_id="42",
        email=None,
        email_verified=False,
    )
    _patch_yandex(monkeypatch, userinfo=userinfo)

    state = await _do_authorize(client)
    r = await client.get(
        "/api/v1/auth/oauth/yandex/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    fragment = parse_qs(urlparse(r.headers["location"]).fragment)
    assert fragment["error"] == ["email_missing"]


# ═══════════════════════════════════════════════════════════════════════════
# Feature flag: oauth_enabled=False
# ═══════════════════════════════════════════════════════════════════════════


async def test_oauth_disabled_returns_404(
    db_session,
    email_sender,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    При oauth_enabled=False роутер НЕ монтируется — все /auth/oauth/* → 404.

    Это критично для сертифицированного контура: клиент не должен даже
    узнать, что такая функциональность существует.
    """
    monkeypatch.setenv("OAUTH_ENABLED", "false")
    get_settings.cache_clear()

    app = create_app()

    async def override_get_db():
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
        # providers
        r = await ac.get("/api/v1/auth/oauth/providers")
        assert r.status_code == 404, r.text
        # authorize
        r = await ac.get(
            "/api/v1/auth/oauth/yandex/authorize",
            follow_redirects=False,
        )
        assert r.status_code == 404
        # В OpenAPI тоже нет
        r = await ac.get("/openapi.json")
        if r.status_code == 200:
            paths = r.json().get("paths", {})
            assert not any(
                "/auth/oauth" in p for p in paths
            ), f"oauth paths leaked: {[p for p in paths if 'oauth' in p]}"