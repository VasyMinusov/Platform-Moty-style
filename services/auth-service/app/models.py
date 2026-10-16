"""
SQLAlchemy 2.0 модели для auth-сервиса.

Требования:
- Полная типизация через Mapped[T] и mapped_column()
- Использование Annotated для переиспользуемых типов
- NIST SP 800-63B Rev 4: session metadata, amr, rate limiting
- ГОСТ Р 34.10-2012: хранение ключей и подписей (опционально)

ВАЖНО: для production использовать Alembic для миграций.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ═══════════════════════════════════════════════════════════════════════════
# Annotated типы (переиспользуемые)
# ═══════════════════════════════════════════════════════════════════════════

# Primary key: BigInteger для user_id (аудит-требование)
intpk = Annotated[int, mapped_column(BigInteger, primary_key=True, autoincrement=True)]

# Timestamps: timezone-aware UTC (NIST)
timestamp = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now()),
]

# Timestamp с возможностью NULL (для locked_until, revoked_at)
nullable_timestamp = Annotated[
    datetime | None,
    mapped_column(DateTime(timezone=True), nullable=True),
]

# Email: 255 символов, unique (RFC 5321)
email_type = Annotated[str, mapped_column(String(255), unique=True, index=True)]


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════


class UserStatus(str, Enum):
    """Статус пользователя."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING_VERIFICATION = "pending_verification"


class AuthMethod(str, Enum):
    """
    Методы аутентификации (NIST amr claim).

    NIST SP 800-63B Rev 4 §4.2:
    Authentication Methods References (amr) — массив строк,
    указывающих, какие методы использовались.
    """

    PASSWORD = "pwd"
    OTP = "otp"
    WEBAUTHN = "webauthn"
    RECOVERY = "recovery"


class AuditAction(str, Enum):
    """Действия для аудит-лога."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    TOKEN_REFRESH = "token_refresh"
    TOKEN_REVOKE = "token_revoke"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    USER_UPDATED = "user_updated"
    USER_REGISTERED = "user_registered"
    # ── Email verification / password reset ──
    EMAIL_VERIFICATION_SENT = "email_verification_sent"
    EMAIL_VERIFIED = "email_verified"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"


# ═══════════════════════════════════════════════════════════════════════════
# User
# ═══════════════════════════════════════════════════════════════════════════


class User(Base):
    """
    Пользователь auth-сервиса.

    NIST SP 800-63B Rev 4:
    - Хранение только хеша пароля (Argon2id)
    - failed_attempts для rate limiting
    - must_change_password для forced change при compromise
    - amr для отслеживания методов аутентификации
    """

    __tablename__ = "users"

    # ── Primary ──────────────────────────────────────────────────────────
    id: Mapped[intpk]

    # ── Identity ─────────────────────────────────────────────────────────
    email: Mapped[email_type]
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Хеш пароля (Argon2id PHC-строка)
    # NIST: SHALL NOT store plaintext passwords
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Status ───────────────────────────────────────────────────────────
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, name="user_status", native_enum=True),
        default=UserStatus.PENDING_VERIFICATION,
        index=True,
    )

    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # NIST: force password change on evidence of compromise
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    # Роль администратора. Даёт доступ к /admin/* (unlock, revoke-sessions,
    # просмотр audit). Изменяется ТОЛЬКО через CLI-скрипт
    # `python -m app.scripts.promote_admin --email <...>` — эндпоинта
    # для самостоятельного повышения нет.
    #
    # server_default="false" нужен для миграции: существующие строки
    # получат false, а не NULL (иначе NOT NULL violation).
    #
    # Без индекса: админов в системе единицы, фильтр "все админы" —
    # не горячий путь.
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )

    # NIST: password rotation SHALL NOT be periodic
    # Но храним timestamp для аудита
    password_changed_at: Mapped[nullable_timestamp]

    # ── Rate limiting (NIST §5.2.2) ──────────────────────────────────────
    # NIST: SHALL implement rate limiting on failed attempts
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[nullable_timestamp]
    last_failed_attempt: Mapped[nullable_timestamp]

    # ── Auth methods (amr) ───────────────────────────────────────────────
    # NIST: authentication methods references
    # Храним как comma-separated (для простоты; в prod — JSONB)
    auth_methods: Mapped[str | None] = mapped_column(String(255), nullable=True, default="pwd")

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at: Mapped[timestamp]
    updated_at: Mapped[timestamp] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[nullable_timestamp]

    # ── Relationships ────────────────────────────────────────────────────
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",  # не загружать автоматически
    )
    # Один пользователь — максимум один MFA-девайс (uselist=False).
    # lazy="selectin" — при загрузке User сразу подтягивается девайс,
    # это нужно для проверки user.is_mfa_enabled в login (без N+1).
    mfa_device: Mapped[MFADevice | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    # Один пользователь — много OAuth-привязок (Яндекс + Google + ...).
    # lazy="noload" — не тянем автоматически: в 99% запросов OAuth-аккаунты
    # не нужны, а JOIN на каждое чтение User — дорого.
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    # ── Indexes ──────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_users_status_created", "status", "created_at"),
        Index("ix_users_locked_until", "locked_until"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, status={self.status.value})>"

    # ── Business logic ───────────────────────────────────────────────────
    @property
    def is_locked(self) -> bool:
        """Проверить, заблокирован ли аккаунт."""
        if self.locked_until is None:
            return False
        return datetime.now(UTC) < self.locked_until

    def get_amr(self) -> list[str]:
        """Получить список методов аутентификации."""
        if not self.auth_methods:
            return ["pwd"]
        return self.auth_methods.split(",")


# ═══════════════════════════════════════════════════════════════════════════
# RefreshToken
# ═══════════════════════════════════════════════════════════════════════════


class RefreshToken(Base):
    """
    Refresh-токен с возможностью revocation.

    NIST SP 800-63B Rev 4 §7.2:
    - Session secrets SHALL be non-persistent
    - Session SHALL NOT be extended past AAL timeouts

    Реализация:
    - jti (JWT ID) — уникальный идентификатор токена
    - revoked — флаг для принудительного отзыва
    - used — для одноразового использования (rotation)
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # JWT ID — связывает с claims.jti
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Session ID — связывает access и refresh
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # Хеш токена (не храним сам токен — NIST)
    # Для production: HMAC-Стрибог или SHA-256
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # ── Status ───────────────────────────────────────────────────────────
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_at: Mapped[nullable_timestamp]
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Rotation: использованный токен помечается used
    used: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Metadata ─────────────────────────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at: Mapped[timestamp]
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_used_at: Mapped[nullable_timestamp]

    # ── Relationships ────────────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_user_session", "user_id", "session_id"),
        Index("ix_refresh_tokens_active", "user_id", "revoked", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken(jti={self.jti[:8]}..., user_id={self.user_id})>"

    @property
    def is_valid(self) -> bool:
        """Проверить валидность токена."""
        if self.revoked or self.used:
            return False
        return datetime.now(UTC) < self.expires_at


# ═══════════════════════════════════════════════════════════════════════════
# AuditLog
# ═══════════════════════════════════════════════════════════════════════════


class AuditLog(Base):
    """
    Аудит-лог действий.

    NIST SP 800-63B Rev 4 §5.2.2:
    SHALL maintain a record of authentication attempts

    Храним:
    - action: что произошло
    - success: успех/неудача
    - metadata_json: JSONB с контекстом (reason, session_id, target_user_id и т.д.)

    metadata_json — JSONB (не Text):
    - типизированный доступ в SQL (`metadata_json->>'reason'`)
    - GIN-индекс для поиска по ключам (`WHERE metadata_json @> '{"reason":"replay"}'`)
    - Postgres валидирует JSON на входе — мусор не запишется
    """

    __tablename__ = "audit_logs"

    id: Mapped[intpk]
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction, name="audit_action", native_enum=True),
        index=True,
    )

    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Контекст: reason, session_id, target_user_id, used_backup и т.п.
    # JSONB: индексируется GIN, доступен через ->>, ->>, @>.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Correlation ID для сквозной трассировки
    correlation_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[timestamp]

    # ── Relationships ────────────────────────────────────────────────────
    user: Mapped[User | None] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action", "created_at"),
        Index("ix_audit_logs_created", "created_at"),
        # GIN-индекс для поиска по ключам JSONB.
        # PostgreSQL 12+: jsonb_path_ops — компактнее и быстрее для @>,
        # но не поддерживает ?, ?|, ?&. Для аудит-запросов @> достаточно.
        Index(
            "ix_audit_logs_metadata",
            "metadata_json",
            postgresql_using="gin",
            postgresql_ops={"metadata_json": "jsonb_path_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action.value}, success={self.success})>"


# ═══════════════════════════════════════════════════════════════════════════
# GOSTKeyPair (опционально для сертифицированного контура)
# ═══════════════════════════════════════════════════════════════════════════


class GOSTKeyPair(Base):
    """
    Пара ключей ГОСТ Р 34.10-2012 для подписи JWT.

    Для production:
    - Приватный ключ хранится в HSM/Vault
    - В БД — только public_key и metadata
    - key_id связывает с JWT header (kid)

    ГОСТ Р 34.10-2012: ЭЦП на эллиптических кривых.
    """

    __tablename__ = "gost_key_pairs"

    id: Mapped[intpk]
    key_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Публичный ключ (hex-encoded)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Алгоритм: GOST3410-2012-256 / GOST3410-2012-512
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)

    # Для ротации ключей
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    activated_at: Mapped[timestamp]
    expires_at: Mapped[nullable_timestamp]
    rotated_at: Mapped[nullable_timestamp]

    created_at: Mapped[timestamp]

    def __repr__(self) -> str:
        return f"<GOSTKeyPair(key_id={self.key_id}, algorithm={self.algorithm})>"


# ═══════════════════════════════════════════════════════════════════════════
# MFADevice
# ═══════════════════════════════════════════════════════════════════════════


class MFADevice(Base):
    """
    MFA-устройство пользователя (TOTP).

    Один пользователь — максимум один девайс (unique FK на user_id).
    Это упрощает flow и достаточно для auth-сервиса: если нужен
    второй фактор — перевыпускаем secret.

    Хранение секрета:
    - `secret_encrypted` — base64-строка с JSON от EncryptedPayload
      (профиль AES-GCM / GOST-Кузнечик, см. app.security.encryption).
    - AAD = f"mfa:{user_id}" — привязка к пользователю: расшифровка
      секрета чужого пользователя невозможна без совпадения AAD.

    Backup-коды:
    - `backup_codes_hash` — JSON-массив HMAC-SHA256 хешей.
    - Используем быстрый хеш (не Argon2id), потому что backup-коды
      имеют высокую энтропию (~49 бит) и одноразовые: перебор
      не имеет смысла, а медленный хеш даёт DoS-вектор при verify.
    - При использовании код удаляется из массива (one-time use).

    Lifecycle:
    - POST /users/me/mfa/setup → создаётся запись с confirmed_at=NULL.
    - POST /users/me/mfa/verify → confirmed_at=now, backup-коды выдаются.
    - POST /users/me/mfa/disable → запись удаляется.

    NIST SP 800-63B Rev 4 §4.2: amr SHALL содержать список методов;
    после включения MFA `user.auth_methods = "pwd,otp"`.
    """

    __tablename__ = "mfa_devices"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    # Зашифрованный TOTP-секрет (JSON от EncryptedPayload.to_dict()).
    # Plaintext secret НЕ хранится нигде — только в момент setup возвращается клиенту.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # NULL = setup инициирован, но verify не пройден (неактивен).
    confirmed_at: Mapped[nullable_timestamp]

    # JSON-массив HMAC-SHA256 хешей backup-кодов. NULL до подтверждения.
    backup_codes_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Аудит: когда последний раз устройство успешно использовалось.
    last_used_at: Mapped[nullable_timestamp]

    # Номер последнего успешно использованного TOTP-шага.
    #
    # TOTP-код — это HMAC(secret, step), где step = unix_time // 30.
    # Валидное окно (mfa_totp_valid_window=1) принимает коды для
    # step-1, step, step+1. Без этой колонки один и тот же 6-значный
    # код можно использовать повторно в течение ~90 секунд (replay).
    #
    # NIST SP 800-63B Rev 4 §5.1.2:
    # "The verifier SHALL NOT accept the same OTP more than once."
    #
    # Логика: при успешном verify сохраняем step. При следующем verify
    # принимаем только step'ы СТРОГО больше сохранённого.
    # NULL = ни один код ещё не использовался (свежий setup).
    last_used_totp_step: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    created_at: Mapped[timestamp]

    # ── Relationships ────────────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="mfa_device")

    def __repr__(self) -> str:
        status = "confirmed" if self.confirmed_at else "pending"
        return f"<MFADevice(user_id={self.user_id}, status={status})>"

    # ── Business logic ───────────────────────────────────────────────────
    @property
    def is_confirmed(self) -> bool:
        """True, если setup завершён и MFA активен."""
        return self.confirmed_at is not None


# ═══════════════════════════════════════════════════════════════════════════
# EmailActionToken (verify email / password reset)
# ═══════════════════════════════════════════════════════════════════════════


class EmailActionType(str, Enum):
    """Тип действия, к которому привязан одноразовый токен."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class EmailActionToken(Base):
    """
    Одноразовый токен для email-действий (verify email / reset password).

    Хранится только HMAC-хеш: plaintext уходит в письмо и живёт только там.
    `used_at` = NULL означает активный токен; при confirm помечается now().
    В `_invalidate_active_tokens` все активные токены того же типа
    помечаются used_at, чтобы старые ссылки перестали работать.
    """

    __tablename__ = "email_action_tokens"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # HMAC-SHA256 hex (64 символа) — с запасом 128.
    token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )

    action: Mapped[EmailActionType] = mapped_column(
        SQLEnum(EmailActionType, name="email_action_type", native_enum=True),
        index=True,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[nullable_timestamp]

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[timestamp]

    user: Mapped[User] = relationship()

    __table_args__ = (
        Index("ix_email_action_tokens_user_action", "user_id", "action"),
    )

    @property
    def is_valid(self) -> bool:
        """Токен активен, не использован и не истёк."""
        if self.used_at is not None:
            return False
        return datetime.now(UTC) < self.expires_at


# ═══════════════════════════════════════════════════════════════════════════
# OAuthAccount
# ═══════════════════════════════════════════════════════════════════════════


class OAuthAccount(Base):
    """
    Привязка пользователя к внешнему OAuth-провайдеру (Яндекс, Google, ...).

    Модель — many-to-one: один User может иметь несколько OAuth-привязок,
    но в рамках одного провайдера — не более одной (см. unique-индексы).

    Почему не храним access/refresh провайдера:
    - Наша задача — "войти через провайдера", а не "работать от его имени".
    - Хранение = дополнительная поверхность атаки.
    - NIST SP 800-63B Rev 4 §5.2.2: минимизация хранимых секретов.

    Если понадобится offline-доступ к API провайдера (например, импорт
    из Яндекс.Диска) — добавим поля `access_token_encrypted`,
    `refresh_token_encrypted`, `expires_at` и флаг `scopes_offline`.
    """

    __tablename__ = "oauth_accounts"

    id: Mapped[intpk]
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Slug провайдера: "yandex", "google". Связывает с реализацией
    # OAuthProvider. Строка, не enum — добавление провайдера не требует
    # миграции.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # ID пользователя у провайдера (у Яндекса — "id" из /userinfo).
    # Строка, не int: разные провайдеры возвращают разное.
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Email от провайдера — только для аудита/UI. НЕ использовать как
    # источник истины: провайдер мог вернуть неподтверждённый email.
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Snapshot на момент привязки. Провайдер может менять отображаемое
    # имя — для аудита важно "что было".
    provider_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[timestamp]
    last_login_at: Mapped[nullable_timestamp]

    # ── Relationships ────────────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="oauth_accounts")

    __table_args__ = (
        # Один User — не более одной привязки к конкретному провайдеру.
        # Защита от race: два параллельных callback'а создадут одну запись,
        # второй упадёт с IntegrityError (роутер вернёт 409).
        Index(
            "ix_oauth_accounts_user_provider",
            "user_id",
            "provider",
            unique=True,
        ),
        # Обратный поиск: "кто привязан к yandex:<id>?". Уникальный —
        # провайдер гарантирует уникальность id.
        Index(
            "ix_oauth_accounts_provider_uid",
            "provider",
            "provider_user_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<OAuthAccount(user_id={self.user_id}, provider={self.provider})>"

