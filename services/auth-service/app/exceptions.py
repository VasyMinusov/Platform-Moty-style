"""
Исключения и обработчики ошибок.

Соответствие RFC 9457 (Problem Details for HTTP APIs) — замена RFC 7807.

Все ошибки отдаются в формате:
    Content-Type: application/problem+json
    {
        "type": "https://api.example.com/problems/authentication-failed",
        "title": "Authentication Failed",
        "status": 401,
        "detail": "The provided credentials are invalid.",
        "instance": "/api/v1/auth/login",
        "correlation_id": "a1b2c3d4"
    }
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import get_correlation_id, get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Base ProblemError
# ═══════════════════════════════════════════════════════════════════════════


class ProblemError(Exception):
    """
    Базовое исключение в формате RFC 9457.

    Атрибуты:
        status_code: HTTP статус
        problem_type: URI типа проблемы (extension RFC 9457)
        title: Краткое описание (человекочитаемое)
        detail: Детали конкретного случая
        instance: URI запроса (заполняется в обработчике)
        extensions: Дополнительные поля (correlation_id, errors и т.д.)
    """

    def __init__(
        self,
        status_code: int,
        problem_type: str,
        title: str,
        detail: str | None = None,
        instance: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.problem_type = problem_type
        self.title = title
        self.detail = detail
        self.instance = instance
        self.extensions: dict[str, Any] = extensions or {}
        super().__init__(title)

    def to_problem_detail(self, request_path: str | None = None) -> dict[str, Any]:
        """
        Сериализовать в RFC 9457 Problem Details JSON.

        ВАЖНО: не включаем stack trace или внутренние детали —
        это может раскрыть информацию о системе.
        """
        problem: dict[str, Any] = {
            "type": self.problem_type,
            "title": self.title,
            "status": self.status_code,
        }

        if self.detail:
            problem["detail"] = self.detail

        # instance — URI конкретного случая (путь запроса)
        if self.instance or request_path:
            problem["instance"] = self.instance or request_path

        # correlation_id — для сквозной трассировки
        correlation_id = get_correlation_id()
        if correlation_id:
            problem["correlation_id"] = correlation_id

        # Extensions (RFC 9457 §3.2)
        problem.update(self.extensions)

        return problem


# ═══════════════════════════════════════════════════════════════════════════
# Конкретные исключения
# ═══════════════════════════════════════════════════════════════════════════


class AuthenticationFailed(ProblemError):
    """
    Ошибка аутентификации (401).

    NIST SP 800-63B Rev 4: generic message для предотвращения
    user enumeration. Не различаем "неверный пароль" и "пользователь не найден".
    """

    def __init__(self, detail: str = "Invalid credentials.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            problem_type="https://api.auth-service.local/problems/authentication-failed",
            title="Authentication Failed",
            detail=detail,
            extensions={"www_authenticate": "Bearer"},
        )


class AccountLocked(ProblemError):
    """Аккаунт заблокирован (423 Locked)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_423_LOCKED,
            problem_type="https://api.auth-service.local/problems/account-locked",
            title="Account Locked",
            detail="Too many failed attempts. Please try again later.",
            extensions={"retry_after": retry_after},
        )


class AccountDisabled(ProblemError):
    """Аккаунт отключён (403)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            problem_type="https://api.auth-service.local/problems/account-disabled",
            title="Account Disabled",
            detail="This account has been disabled. Contact support.",
        )


class MFARequired(ProblemError):
    """
    Операция требует MFA (403).

    NIST SP 800-63B Rev 4 §5.2.2: критичные операции (смена пароля,
    управление MFA, sensitive actions) SHALL требовать MFA. Проверка
    выполняется по claim `amr` текущего access-токена, а не по
    user.auth_methods в БД: если пользователь включил MFA в одной
    сессии, но в другой сессии прошёл только по паролю — доступ
    к критичным операциям SHALL быть заблокирован.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            problem_type="https://api.auth-service.local/problems/mfa-required",
            title="MFA Required",
            detail="This operation requires multi-factor authentication.",
            extensions={"required_methods": ["otp", "webauthn"]},
        )


class InvalidToken(ProblemError):
    """Невалидный токен (401)."""

    def __init__(self, detail: str = "Invalid or expired token.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            problem_type="https://api.auth-service.local/problems/invalid-token",
            title="Invalid Token",
            detail=detail,
        )


class RateLimitExceeded(ProblemError):
    """Превышен rate limit (429)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            problem_type="https://api.auth-service.local/problems/rate-limit-exceeded",
            title="Rate Limit Exceeded",
            detail="Too many requests. Please retry later.",
            extensions={"retry_after": retry_after},
        )


class ResourceNotFound(ProblemError):
    """Ресурс не найден (404)."""

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            problem_type="https://api.auth-service.local/problems/resource-not-found",
            title="Resource Not Found",
            detail=f"{resource} not found.",
        )


class ResourceConflict(ProblemError):
    """Конфликт ресурсов (409)."""

    def __init__(self, detail: str = "Resource already exists.") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            problem_type="https://api.auth-service.local/problems/resource-conflict",
            title="Resource Conflict",
            detail=detail,
        )


class PasswordPolicyViolation(ProblemError):
    """
    Нарушение парольной политики (422).

    NIST SP 800-63B Rev 4: возвращаем конкретные ошибки валидации.
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            problem_type="https://api.auth-service.local/problems/password-policy",
            title="Password Policy Violation",
            detail="The provided password does not meet policy requirements.",
            extensions={"errors": errors},
        )


class ValidationError(ProblemError):
    """Ошибка валидации входных данных (422)."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            problem_type="https://api.auth-service.local/problems/validation-error",
            title="Validation Error",
            detail="One or more fields failed validation.",
            extensions={"errors": errors},
        )


class InvalidEmailToken(ProblemError):
    """
    Невалидный/истёкший/использованный email-токен (400).

    Generic: не раскрываем, что именно не так (истёк vs уже использован
    vs не существует) — anti-enumeration.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            problem_type="https://api.auth-service.local/problems/invalid-email-token",
            title="Invalid Email Token",
            detail="The token is invalid, expired, or already used.",
        )
# ═══════════════════════════════════════════════════════════════════════════
# Обработчики исключений
# ═══════════════════════════════════════════════════════════════════════════


async def problem_exception_handler(request: Request, exc: ProblemError) -> JSONResponse:
    """
    Обработчик ProblemError.

    Логирует server-side полную информацию (включая stack trace),
    клиенту отдаёт только RFC 9457 Problem Details.
    """
    log.error(
        "problem_exception",
        problem_type=exc.problem_type,
        status=exc.status_code,
        title=exc.title,
        path=request.url.path,
        method=request.method,
    )

    problem = exc.to_problem_detail(request_path=str(request.url.path))

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Обработчик стандартного HTTPException.

    Конвертирует в RFC 9457 формат.
    """
    # Если detail — dict, используем его как extension
    extensions: dict[str, Any] = {}
    detail: str | None
    if isinstance(exc.detail, dict):
        extensions = exc.detail
        detail = None
    else:
        detail = str(exc.detail)

    problem: dict[str, Any] = {
        "type": "about:blank",  # RFC 9457: default type
        "title": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
        "status": exc.status_code,
        "instance": str(request.url.path),
    }

    if detail:
        problem["detail"] = detail

    correlation_id = get_correlation_id()
    if correlation_id:
        problem["correlation_id"] = correlation_id

    problem.update(extensions)

    # Логируем 5xx как error, 4xx как warning
    log_fn = log.error if exc.status_code >= 500 else log.warning
    log_fn(
        "http_exception",
        status=exc.status_code,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Обработчик ошибок валидации Pydantic.

    RFC 9457 §3.2: extension "errors" — массив с деталями каждой ошибки.
    """
    errors: list[dict[str, Any]] = []
    for error in exc.errors():
        errors.append(
            {
                "pointer": "/" + "/".join(str(loc) for loc in error["loc"]),
                "detail": error["msg"],
                "code": error["type"],
            }
        )

    problem: dict[str, Any] = {
        "type": "https://api.auth-service.local/problems/validation-error",
        "title": "Validation Error",
        "status": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "detail": "Request validation failed.",
        "instance": str(request.url.path),
        "errors": errors,
    }

    correlation_id = get_correlation_id()
    if correlation_id:
        problem["correlation_id"] = correlation_id

    log.warning(
        "validation_error",
        path=request.url.path,
        errors=errors,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=problem,
        media_type="application/problem+json",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Обработчик необработанных исключений (500).

    ВАЖНО: не раскрываем stack trace клиенту.
    """
    log.exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_info=True,
    )

    problem: dict[str, Any] = {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "detail": "An unexpected error occurred. Please try again later.",
        "instance": str(request.url.path),
    }

    correlation_id = get_correlation_id()
    if correlation_id:
        problem["correlation_id"] = correlation_id

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=problem,
        media_type="application/problem+json",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Регистрация обработчиков
# ═══════════════════════════════════════════════════════════════════════════


def register_exception_handlers(app: FastAPI) -> None:
    """
    Зарегистрировать все обработчики исключений.

    Вызывается из main.py после создания app.

    NB: mypy ругается на несовместимость типов обработчиков —
    Starlette типизирует add_exception_handler с базовым Exception,
    а мы передаём более конкретные типы (ProblemError, HTTPException,
    RequestValidationError). Это ограничение типов Starlette,
    не наш баг. Для обработчика базового Exception тип совпадает —
    поэтому type: ignore там не нужен.
    """
    app.add_exception_handler(
        ProblemError,
        problem_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)

    log.info("exception_handlers_registered")
