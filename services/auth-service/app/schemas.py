"""
Pydantic v2 схемы для auth-сервиса.

Принципы:
- Разделение request/response (security boundary)
- Generic модели для переиспользования
- Валидация паролей через NIST SP 800-63B Rev 4
- from_attributes=True для ORM-объектов

ВАЖНО про пароль в UserCreate:
Схема НЕ валидирует политику пароля (min length, HIBP, context words).
Причина: полная валидация требует async (HIBP API) и Settings
(min length зависит от MFA-контекста). Это делается в роутере
через app.security.passwords.validate_password().

Схема проверяет только жёсткий пол (непустой пароль, max 64) —
чтобы отсечь заведомо мусорные запросы до сетевого вызова.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

# ═══════════════════════════════════════════════════════════════════════════
# Annotated типы для переиспользования
# ═══════════════════════════════════════════════════════════════════════════

# Email: валидация формата
Email = Annotated[EmailStr, StringConstraints(max_length=255)]

# Username: 3-64 символа, alphanumeric + underscore
Username = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_]+$",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# Базовые схемы
# ═══════════════════════════════════════════════════════════════════════════


class BaseSchema(BaseModel):
    """Базовая схема с общей конфигурацией."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",  # Запрещаем неизвестные поля (security boundary)
    )


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════


class UserStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING_VERIFICATION = "pending_verification"


class TokenTypeEnum(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


# ═══════════════════════════════════════════════════════════════════════════
# User schemas
# ═══════════════════════════════════════════════════════════════════════════


class UserBase(BaseSchema):
    """Общие поля для всех user-схем."""

    email: Email
    username: Username


class UserCreate(UserBase):
    """
    Схема регистрации.

    Security boundary: НЕТ id, НЕТ status, НЕТ created_at.

    Пароль:
    - Hard floor: непустой, ≤ 64 символов (NIST: SHALL permit ≥ 64).
    - Max_length enforced здесь.
    - Минимальная длина (15 для single-factor, 8 для MFA) и blocklist
      screening — в роутере через validate_password() (async, HIBP).
    - Composition rules НЕ проверяются — NIST SHALL NOT.

    Почему нет min_length=15 в схеме:
    Значение зависит от контекста (single-factor vs MFA). Схема не
    знает контекст. Если поставить 15 — сломаем MFA-регистрацию.
    Если поставить 8 — OpenAPI-контракт будет врать для
    single-factor. Компромисс: жёсткий пол 1 (непустой), max 64,
    полная политика — в роутере.
    """

    password: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Пароль. Минимум 15 символов для single-factor (NIST SP 800-63B Rev 4), "
            "8 для MFA. Blocklist screening (HIBP) выполняется на сервере. "
            "Composition rules (регистр/цифры/спецсимволы) не применяются."
        ),
    )


class UserRead(UserBase):
    """Схема ответа с данными пользователя."""

    id: int
    status: UserStatusEnum
    is_email_verified: bool
    is_mfa_enabled: bool
    must_change_password: bool
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None = None

    # НЕ включаем: password_hash, failed_attempts, locked_until


class UserUpdate(BaseSchema):
    """Схема обновления профиля (PATCH)."""

    email: Email | None = None
    username: Username | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Auth schemas
# ═══════════════════════════════════════════════════════════════════════════


class LoginRequest(BaseSchema):
    """Схема логина."""

    email: Email
    password: str = Field(min_length=1)


class TokenResponse(BaseSchema):
    """Схема ответа с токенами."""

    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    session_id: str


class RefreshRequest(BaseSchema):
    """Схема refresh токена."""

    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseSchema):
    """Схема logout."""

    refresh_token: str = Field(min_length=1)
    all_sessions: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Password schemas
# ═══════════════════════════════════════════════════════════════════════════


class PasswordChangeRequest(BaseSchema):
    """Схема смены пароля."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Новый пароль. Полная валидация (min 15, HIBP) — на сервере "
            "в роутере через validate_password()."
        ),
    )

    @model_validator(mode="after")
    def validate_new_password(self) -> PasswordChangeRequest:
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from current")
        return self


class PasswordResetRequest(BaseSchema):
    """Схема запроса сброса пароля."""

    email: Email


class PasswordResetConfirm(BaseSchema):
    """Схема подтверждения сброса пароля."""

    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=64)


# ═══════════════════════════════════════════════════════════════════════════
# Session schemas
# ═══════════════════════════════════════════════════════════════════════════


class SessionRead(BaseSchema):
    """Схема сессии (для отображения в UI)."""

    session_id: str
    created_at: datetime
    last_used_at: datetime | None
    ip_address: str | None
    user_agent: str | None
    is_current: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Generic pagination
# ═══════════════════════════════════════════════════════════════════════════

T = TypeVar("T")


class PaginationParams(BaseSchema):
    """Параметры пагинации."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedResponse(BaseSchema, Generic[T]):
    """
    Generic пагинированный ответ.

    Использование:
        PaginatedResponse[UserRead](
            items=[...],
            total=100,
            page=1,
            per_page=20,
        )
    """

    items: list[T]
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return (self.total + self.per_page - 1) // self.per_page

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


# ═══════════════════════════════════════════════════════════════════════════
# Generic API response (OWASP A07:2025 - generic messages)
# ═══════════════════════════════════════════════════════════════════════════


class MessageResponse(BaseSchema):
    """
    Generic сообщение.

    OWASP A07:2025: одинаковые сообщения для всех исходов
    (предотвращение enumeration).
    """

    message: str = Field(
        default="If the provided information is correct, you will receive further instructions."
    )


class ErrorResponse(BaseSchema):
    """Схема ошибки."""

    detail: str
    code: str | None = None
    correlation_id: str | None = None

# ═══════════════════════════════════════════════════════════════════════════
# Audit log (для admin-эндпоинтов)
# ═══════════════════════════════════════════════════════════════════════════


class AuditLogRead(BaseSchema):
    """
    Запись аудит-лога.

    Возвращается из `GET /admin/users/{id}/audit`. Все поля —
    read-only, изменять audit_logs через API нельзя.
    """

    id: int
    user_id: int | None = None
    action: str  # AuditAction.value (str, а не Enum — клиенту проще)
    success: bool
    metadata_json: dict[str, Any] | None = None
    correlation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

# ═══════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════


class HealthResponse(BaseSchema):
    """Схема health check."""

    status: Literal["ok", "degraded", "error"]
    version: str
    database: bool
    timestamp: datetime


# ═══════════════════════════════════════════════════════════════════════════
# MFA (TOTP)
# ═══════════════════════════════════════════════════════════════════════════

# Формат кода: TOTP — 6 цифр, backup-код — 11 символов (10 base32 + дефис).
# Одно поле принимает оба варианта — клиент не должен знать, какой
# тип проверяется первым (defense in depth: не раскрываем наличие backup-кода).
MFACode = Annotated[
    str,
    StringConstraints(min_length=6, max_length=16),
]


class MFASetupResponse(BaseSchema):
    """
    Ответ на инициализацию MFA.

    Возвращает plaintext secret — единственный раз, когда он покидает сервер.
    Клиент обязан сохранить его в приложении-аутентификаторе.

    `otpauth_url` — стандартный URI для QR-кода (RFC не формализован, но
    де-факто стандарт: используется Google Authenticator, Authy, 1Password).
    """

    secret: str
    otpauth_url: str
    issuer: str


class MFAVerifySetupRequest(BaseSchema):
    """Подтверждение настройки MFA: 6-значный TOTP-код."""

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-значный TOTP-код из приложения-аутентификатора.",
    )


class MFAVerifySetupResponse(BaseSchema):
    """
    Успешное подтверждение MFA.

    `backup_codes` возвращаются **один раз**. Клиент должен показать их
    пользователю и предупредить, что они не будут доступны снова.
    """

    message: str
    backup_codes: list[str] = Field(
        description="Одноразовые резервные коды. Сохраните — показываются только один раз.",
    )


class MFADisableRequest(BaseSchema):
    """Отключение MFA требует подтверждения текущим TOTP-кодом."""

    code: MFACode = Field(
        description="TOTP-код (6 цифр) или backup-код (XXXXX-XXXXX).",
    )


class MFAPendingResponse(BaseSchema):
    """
    Ответ /auth/login, когда у пользователя включён MFA.

    Клиент должен:
    1. Запомнить `mfa_token` (в памяти, не в localStorage).
    2. Запросить у пользователя TOTP-код.
    3. POST /auth/mfa/verify с `mfa_token` + `code`.

    `mfa_token` даёт право только на /auth/mfa/verify (typ=mfa_pending).
    Использовать его как access нельзя.
    """

    mfa_required: Literal[True] = True
    mfa_token: str
    expires_in: int = Field(description="TTL mfa_token в секундах (обычно 300).")


class MFALoginVerifyRequest(BaseSchema):
    """
    Обмен mfa_token + код на access/refresh.

    `code` принимает:
    - 6-значный TOTP-код (если приложение-аутентификатор доступно).
    - backup-код (если потерян доступ к аутентификатору).

    Backup-код одноразовый: после успешного использования удаляется.
    """

    mfa_token: str = Field(min_length=1)
    code: MFACode = Field(
        description="TOTP-код (6 цифр) или backup-код (XXXXX-XXXXX).",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Email verification / password reset
# ═══════════════════════════════════════════════════════════════════════════


class VerifyEmailConfirm(BaseSchema):
    """Подтверждение email одноразовым токеном из письма."""

    token: str = Field(min_length=32, max_length=128)


# ═══════════════════════════════════════════════════════════════════════════
# OAuth2
# ═══════════════════════════════════════════════════════════════════════════


class OAuthProviderRead(BaseSchema):
    """
    Публичная информация о провайдере — для UI (кнопки «Войти через ...»).

    Не раскрывает client_id, client_secret, authorize_url с параметрами —
    только slug (для построения URL на клиенте) и display_name.
    """

    slug: str
    display_name: str
