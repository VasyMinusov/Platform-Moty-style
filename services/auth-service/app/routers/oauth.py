"""
OAuth2 через внешних провайдеров (Яндекс).

Эндпоинты (все публичные, БЕЗ Bearer):
- GET /auth/oauth/providers              → [{slug, display_name}]
- GET /auth/oauth/{provider}/authorize   → 302 на провайдера
- GET /auth/oauth/{provider}/callback    → 302 на frontend с токенами

**Feature flag.** Роутер монтируется в `create_app()` **только** если
`settings.oauth_enabled=True`. При `False`:
- `/api/v1/auth/oauth/*` → 404 (роутера нет в стеке);
- эндпоинтов нет в OpenAPI;
- модуль `app.security.oauth` не импортируется никем, кроме этого файла.

Это критично для сертифицированного контура (ГОСТ/ФСБ), где OAuth
через публичных провайдеров обычно запрещён — мы не должны даже
раскрывать факт наличия такой функциональности.

**Возврат токенов.** После успешного callback редиректим на
`{oauth_frontend_callback_url}#access_token=...&refresh_token=...`.
Fragment (`#`) выбран осознанно: он НЕ уходит на сервер, не попадает
в access-логи reverse-proxy, Referer и history API сервера. Клиент
читает его через `window.location.hash`. Это стандарт для SPA.
"""

from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import write_audit
from app.config import get_settings
from app.dependencies import ClientInfo, DBSession
from app.exceptions import ResourceNotFound
from app.logging_config import get_logger
from app.metrics import oauth_logins_total
from app.models import AuditAction, OAuthAccount, User, UserStatus
from app.schemas import OAuthProviderRead
from app.security.jwt_handler import get_jwt_handler
from app.security.oauth import get_enabled_providers, get_provider
from app.security.oauth.base import OAuthProviderError, OAuthUserInfo
from app.security.oauth.state import OAuthStateError, sign_state, verify_state
from app.security.passwords import get_password_hasher
from app.services.session import persist_refresh_token

log = get_logger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


# ═══════════════════════════════════════════════════════════════════════════
# Внутренние утилиты
# ═══════════════════════════════════════════════════════════════════════════


def _build_callback_url(provider_slug: str) -> str:
    """
    Redirect URI, который отправляем провайдеру и проверяем в callback.

    Должен **точно** совпадать со значением, зарегистрированным в консоли
    провайдера — иначе Яндекс вернёт `invalid_request`.
    """
    settings = get_settings()
    base = settings.oauth_public_base_url.rstrip("/")
    return f"{base}{settings.api_prefix}/auth/oauth/{provider_slug}/callback"


def _redirect_to_frontend(
    *,
    error: str | None = None,
    tokens: dict[str, object] | None = None,
) -> RedirectResponse:
    """
    Единая точка редиректа на frontend.

    Успех: `{frontend_url}#access_token=...&refresh_token=...&...`
    Ошибка: `{frontend_url}#error={code}`

    Все ошибки идут через fragment — консистентно с токенами, и клиент
    читает их одним способом.
    """
    settings = get_settings()
    base = settings.oauth_frontend_callback_url

    if error is not None:
        fragment = urlencode({"error": error})
        return RedirectResponse(url=f"{base}#{fragment}", status_code=302)

    if tokens is None:
        # Defensive: не должно случаться, но лучше явная ошибка,
        # чем пустой fragment.
        fragment = urlencode({"error": "internal_error"})
        return RedirectResponse(url=f"{base}#{fragment}", status_code=302)

    fragment = urlencode(
        {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": tokens["token_type"],
            "expires_in": tokens["expires_in"],
            "session_id": tokens["session_id"],
        }
    )
    return RedirectResponse(url=f"{base}#{fragment}", status_code=302)


def _generate_username(userinfo: OAuthUserInfo) -> str:
    """
    Сгенерировать username для нового OAuth-пользователя.

    Формат: `{clean}_{4hex}`, где clean — из userinfo.username / email
    local part / provider_user_id, приведённый к `[a-zA-Z0-9_]`.

    Суффикс 4 hex-символа (65536 вариантов) — статистически достаточно
    против коллизий при небольшом количестве пользователей. При
    коллизии IntegrityError — но такой случай маловероятен, а retry-loop
    усложнил бы код неоправданно.
    """
    import re
    import secrets

    candidates: list[str] = []
    if userinfo.username:
        candidates.append(userinfo.username)
    if userinfo.email and "@" in userinfo.email:
        candidates.append(userinfo.email.split("@", 1)[0])
    candidates.append(userinfo.provider_user_id)

    for candidate in candidates:
        cleaned = re.sub(r"[^a-zA-Z0-9_]", "", candidate)
        if len(cleaned) < 3:
            continue
        # Оставляем место для суффикса `_xxxx` (5 символов),
        # schema допускает максимум 64.
        cleaned = cleaned[:55]
        return f"{cleaned}_{secrets.token_hex(2)}"

    # Экзотический случай: провайдер вернул только не-ASCII id
    return f"oauth_{secrets.token_hex(6)}"


def _random_password_hash() -> str:
    """
    Случайный невосстановимый пароль для OAuth-only user.

    Мы храним NOT NULL `password_hash`, поэтому нужно что-то положить.
    32 байта `token_urlsafe` → ~256 бит энтропии, argon2id — hash.
    Пользователь не знает этот пароль (может сбросить через email,
    если Яндекс-email подтверждён).

    Альтернатива (nullable password_hash) потребовала бы миграции
    и правок `/users/me/password`. Осознанно не идём этим путём —
    ломается инвариант «у всех user есть пароль», от которого
    зависит логика timing-safe verify.
    """
    import secrets

    random_password = secrets.token_urlsafe(32)
    return get_password_hasher().hash(random_password)


# ═══════════════════════════════════════════════════════════════════════════
# GET /auth/oauth/providers
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/providers",
    response_model=list[OAuthProviderRead],
    summary="Список активных OAuth-провайдеров",
    description=(
        "Возвращает только сконфигурированные провайдеры "
        "(client_id и client_secret заданы в Settings). "
        "Для UI: клиент отрисовывает кнопку «Войти через {display_name}»."
    ),
)
async def list_providers() -> list[OAuthProviderRead]:
    """
    Публичный список — без Bearer.

    Не раскрывает client_id/secret — только slug и display_name.
    """
    return [
        OAuthProviderRead(slug=p.slug, display_name=p.display_name)
        for p in get_enabled_providers()
    ]


# ═══════════════════════════════════════════════════════════════════════════
# GET /auth/oauth/{provider}/authorize
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/{provider_slug}/authorize",
    summary="Начать OAuth-flow",
    responses={
        302: {"description": "Redirect на провайдера"},
        404: {"description": "Провайдер неизвестен или не сконфигурирован"},
    },
)
async def oauth_authorize(provider_slug: str) -> RedirectResponse:
    """
    Сгенерировать state и редиректнуть пользователя на провайдера.

    State — подписанный JWT с TTL 5 минут (`oauth_state_ttl_seconds`).
    Провайдер вернёт его без изменений в callback — мы проверим
    подпись и exp (CSRF-защита, RFC 6749 §10.12).
    """
    provider = get_provider(provider_slug)
    if provider is None:
        # Не раскрываем, «неизвестен» или «не сконфигурирован» —
        # одинаковый 404.
        raise ResourceNotFound(resource="OAuth provider")

    state = sign_state(provider=provider_slug)
    redirect_uri = _build_callback_url(provider_slug)

    try:
        authorize_url = provider.build_authorize_url(
            state=state,
            redirect_uri=redirect_uri,
        )
    except OAuthProviderError as exc:
        # build_authorize_url не должен падать, если is_configured=True,
        # но защищаемся от регрессии.
        log.error(
            "oauth_authorize_url_build_failed",
            provider=provider_slug,
            reason=exc.reason,
        )
        oauth_logins_total.labels(
            provider=provider_slug, result="provider_error"
        ).inc()
        raise ResourceNotFound(resource="OAuth provider") from exc

    oauth_logins_total.labels(provider=provider_slug, result="initiated").inc()
    log.info("oauth_authorize_redirect", provider=provider_slug)

    return RedirectResponse(url=authorize_url, status_code=302)


# ═══════════════════════════════════════════════════════════════════════════
# GET /auth/oauth/{provider}/callback
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/{provider_slug}/callback",
    summary="OAuth callback",
    responses={
        302: {
            "description": (
                "Redirect на frontend: `#access_token=...&refresh_token=...` "
                "при успехе, `#error={code}` при ошибке"
            ),
        },
    },
)
async def oauth_callback(
    provider_slug: str,
    code: str,
    state: str,
    db: DBSession,
    client: ClientInfo,
    request: Request,  # noqa: ARG001 — для консистентности middleware; не используется
) -> RedirectResponse:
    """
    Обменять authorization code на токены, найти/создать User + OAuthAccount,
    выдать наш JWT-пару, редиректнуть на frontend.

    Все ошибки → `302 {frontend}#error={code}`. Мы **не** возвращаем
    HTTP-ошибки: пользователь в браузере, а не API-клиент. 4xx/5xx
    показали бы ему JSON-страницу вместо возврата в приложение.
    """
    # ── 1. Провайдер существует? ──────────────────────────────────────────
    provider = get_provider(provider_slug)
    if provider is None:
        # 404 — норм, потому что это ошибка конфигурации, а не user-flow.
        raise ResourceNotFound(resource="OAuth provider")

    # ── 2. State валиден? ────────────────────────────────────────────────
    try:
        verify_state(state, expected_provider=provider_slug)
    except OAuthStateError as exc:
        log.warning(
            "oauth_callback_invalid_state",
            provider=provider_slug,
            reason=str(exc),
        )
        oauth_logins_total.labels(
            provider=provider_slug, result="invalid_state"
        ).inc()
        return _redirect_to_frontend(error="invalid_state")

    # ── 3. Обмен code → tokens → userinfo ────────────────────────────────
    redirect_uri = _build_callback_url(provider_slug)
    try:
        provider_tokens = await provider.exchange_code(
            code=code,
            redirect_uri=redirect_uri,
        )
        userinfo = await provider.fetch_user_info(provider_tokens)
    except OAuthProviderError as exc:
        log.warning(
            "oauth_callback_provider_error",
            provider=provider_slug,
            reason=exc.reason,
            description=exc.description,
        )
        oauth_logins_total.labels(
            provider=provider_slug, result="provider_error"
        ).inc()
        return _redirect_to_frontend(error=exc.reason)

    # ── 4. Существующая привязка? ────────────────────────────────────────
    account_result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider_slug,
            OAuthAccount.provider_user_id == userinfo.provider_user_id,
        )
    )
    account = account_result.scalar_one_or_none()

    now = datetime.now(UTC)

    if account is not None:
        # ── 4a. Существующий OAuth-пользователь ──────────────────────────
        user_result = await db.execute(select(User).where(User.id == account.user_id))
        user = user_result.scalar_one_or_none()

        if user is None:
            # Инвариант нарушен: CASCADE FK должен был удалить OAuthAccount
            # вместе с User. Считаем это багом данных, логируем и отказываем.
            log.error(
                "oauth_account_orphaned",
                provider=provider_slug,
                account_id=account.id,
                user_id=account.user_id,
            )
            oauth_logins_total.labels(
                provider=provider_slug, result="provider_error"
            ).inc()
            return _redirect_to_frontend(error="user_not_found")

        account.last_login_at = now
        oauth_logins_total.labels(
            provider=provider_slug, result="existing_user"
        ).inc()

    else:
        # ── 4b. Новый пользователь ───────────────────────────────────────
        # Q2=(a): не линкуем по email автоматически — иначе takeover
        # через чужой OAuth-аккаунт с подделанным/совпавшим email.
        if not userinfo.email:
            log.warning(
                "oauth_callback_email_missing",
                provider=provider_slug,
                provider_user_id=userinfo.provider_user_id,
            )
            oauth_logins_total.labels(
                provider=provider_slug, result="email_missing"
            ).inc()
            return _redirect_to_frontend(error="email_missing")

        existing_result = await db.execute(
            select(User).where(User.email == userinfo.email)
        )
        if existing_result.scalar_one_or_none() is not None:
            log.warning(
                "oauth_callback_email_taken",
                provider=provider_slug,
                email=userinfo.email,
            )
            oauth_logins_total.labels(
                provider=provider_slug, result="email_already_taken"
            ).inc()
            return _redirect_to_frontend(error="email_already_registered")

        user = User(
            email=userinfo.email,
            username=_generate_username(userinfo),
            password_hash=_random_password_hash(),
            status=UserStatus.ACTIVE,
            is_email_verified=userinfo.email_verified,
            auth_methods="oauth",
            password_changed_at=now,
        )
        db.add(user)

        try:
            await db.flush()  # получить user.id
        except IntegrityError as exc:
            # Race: параллельный callback с тем же email. Отдаём
            # generic-ошибку — retry пользователем решит.
            log.error(
                "oauth_callback_integrity_error",
                provider=provider_slug,
                error=str(exc),
            )
            await db.rollback()
            oauth_logins_total.labels(
                provider=provider_slug, result="email_already_taken"
            ).inc()
            return _redirect_to_frontend(error="email_already_registered")

        account = OAuthAccount(
            user_id=user.id,
            provider=provider_slug,
            provider_user_id=userinfo.provider_user_id,
            provider_email=userinfo.email,
            provider_username=userinfo.username,
            last_login_at=now,
        )
        db.add(account)
        await db.flush()

        oauth_logins_total.labels(
            provider=provider_slug, result="new_user"
        ).inc()

    # ── 5. Обновить last_login_at ────────────────────────────────────────
    user.last_login_at = now

    # ── 6. Выдать нашу JWT-пару ──────────────────────────────────────────
    # amr=["oauth"] — NIST SP 800-63B Rev 4 §4.2. RFC 8176 (amr registry)
    # определяет "oauth" как метод федеративной аутентификации.
    # Это значит:
    #  - require_mfa (проверяет otp/webauthn) НЕ пропустит такого
    #    пользователя на критичные операции без явного MFA-setup.
    #  - Даже если admin promoted OAuth-user'а, админ-эндпоинты
    #    потребуют настоящий второй фактор.
    jwt_handler = get_jwt_handler()
    token_pair = jwt_handler.create_token_pair(
        user_id=user.id,
        amr=["oauth"],
    )

    await persist_refresh_token(
        db,
        user_id=user.id,
        tokens=token_pair,
        client=client,
    )

    # ── 7. Audit ─────────────────────────────────────────────────────────
    await write_audit(
        db,
        user_id=user.id,
        action=AuditAction.LOGIN_SUCCESS,
        success=True,
        client=client,
        metadata={
            "method": "oauth",
            "provider": provider_slug,
            "session_id": token_pair["session_id"],
            "new_user": account.created_at == account.last_login_at,
        },
    )

    oauth_logins_total.labels(provider=provider_slug, result="success").inc()
    log.info(
        "oauth_callback_success",
        provider=provider_slug,
        user_id=user.id,
        session_id=token_pair["session_id"],
    )

    # ── 8. Редирект на frontend с токенами ───────────────────────────────
    return _redirect_to_frontend(tokens=token_pair)
