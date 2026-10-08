"""Простой in-memory rate limiter.

Скользящее окно по IP клиента. Работает только в пределах одного процесса
backend — этого достаточно для MVP (backend запущен одним воркером).

Если backend будет масштабироваться на несколько воркеров/реплик —
заменить хранилище на Redis.
"""
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Правила: (метод, regex пути) -> (лимит, окно в секундах).
# Метод None = любой.
RateRule = tuple[str | None, str, int, int]


DEFAULT_RULES: list[RateRule] = [
    # Логин и регистрация — самые чувствительные.
    ("POST", r"^/auth/login$", 10, 60),
    ("POST", r"^/auth/register$", 5, 300),

    # Старт инстансов и submit — защита от автоперебора.
    ("POST", r"^/challenges/[^/]+/start$", 20, 60),
    ("POST", r"^/challenges/[^/]+/submit$", 30, 60),
    ("POST", r"^/competitions/[^/]+/challenges/[^/]+/start$", 20, 60),
    ("POST", r"^/competitions/[^/]+/challenges/[^/]+/submit$", 30, 60),
    ("POST", r"^/competitions/[^/]+/challenges/[^/]+/hints/[0-9]+/buy$", 20, 60),

    # Заявки и команды.
    ("POST", r"^/competitions/[^/]+/apply$", 10, 300),
    ("POST", r"^/competitions/[^/]+/teams$", 5, 300),
    ("POST", r"^/competitions/[^/]+/teams/[0-9]+/invite$", 30, 300),
    ("POST", r"^/competitions/[^/]+/teams/join-by-code$", 10, 300),

    # Апелляции.
    ("POST", r"^/competitions/[^/]+/appeals$", 5, 600),

    # Загрузка заданий.
    ("POST", r"^/admin/competitions/[^/]+/challenges/upload$", 20, 600),
]


def _client_ip(request: Request) -> str:
    """Определяет IP клиента с учётом X-Forwarded-For (nginx)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _matches(method: str, path: str, rule: RateRule) -> bool:
    import re
    rule_method, pattern, _, _ = rule
    if rule_method and rule_method != method:
        return False
    return re.match(pattern, path) is not None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware для ограничения частоты запросов.

    Накладывается после CORS. Правила задаются в DEFAULT_RULES и могут быть
    переопределены через параметр rules.
    """

    def __init__(self, app, rules: list[RateRule] | None = None):
        super().__init__(app)
        self.rules = rules or DEFAULT_RULES
        self._buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next: Callable):
        method = request.method
        # Берём только путь без query string.
        path = request.url.path

        matched_rule: RateRule | None = None
        for rule in self.rules:
            if _matches(method, path, rule):
                matched_rule = rule
                break

        if matched_rule is None:
            return await call_next(request)

        _, pattern, limit, window = matched_rule
        ip = _client_ip(request)
        bucket_key = (ip, pattern)

        now = time.monotonic()

        with self._lock:
            bucket = self._buckets[bucket_key]
            # Убираем старые записи.
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(bucket[0] + window - now) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Too many requests. Retry in {retry_after}s."},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

        return await call_next(request)