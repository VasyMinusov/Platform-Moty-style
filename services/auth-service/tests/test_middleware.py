"""
Тесты ActiveRequestsMiddleware: счётчик активных запросов + graceful shutdown.
"""

import asyncio

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.middleware import (
    ActiveRequestsMiddleware,
    get_active_requests_middleware,
    reset_active_requests_middleware,
)


# ═══════════════════════════════════════════════════════════════════════════
# Вспомогательные ASGI-приложения
# ═══════════════════════════════════════════════════════════════════════════


def _http_scope() -> Scope:
    """Минимальный HTTP-scope для проверки middleware."""
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }


async def _noop_receive() -> Message:
    return {"type": "http.request"}


async def _noop_send(message: Message) -> None:
    pass


class _BlockingApp:
    """
    ASGI-приложение, которое «висит» до сигнала event.

    Используется, чтобы проверить wait_for_zero при ненулевом счётчике.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.entered.set()
        await self.release.wait()


class _InstantApp:
    """ASGI-приложение, которое завершается мгновенно."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        return


# ═══════════════════════════════════════════════════════════════════════════
# Базовая механика счётчика
# ═══════════════════════════════════════════════════════════════════════════


async def test_active_count_zero_when_idle() -> None:
    """На свежем middleware счётчик нулевой."""
    mw = ActiveRequestsMiddleware(_InstantApp())
    assert mw.active_count == 0


async def test_active_count_increments_during_request() -> None:
    """Во время запроса счётчик = 1, после — 0."""
    app = _BlockingApp()
    mw = ActiveRequestsMiddleware(app)

    # Запускаем запрос в фоне — он «зависнет» внутри app.
    task = asyncio.create_task(
        mw(_http_scope(), _noop_receive, _noop_send)
    )
    await app.entered.wait()

    assert mw.active_count == 1

    # Отпускаем app — запрос завершается, счётчик обнуляется.
    app.release.set()
    await task

    assert mw.active_count == 0


async def test_active_count_decrements_on_exception() -> None:
    """Если app бросает — счётчик всё равно декрементится (finally)."""

    class _FailingApp:
        async def __call__(
            self, scope: Scope, receive: Receive, send: Send
        ) -> None:
            raise RuntimeError("boom")

    mw = ActiveRequestsMiddleware(_FailingApp())

    with pytest.raises(RuntimeError, match="boom"):
        await mw(_http_scope(), _noop_receive, _noop_send)

    assert mw.active_count == 0


async def test_non_http_scope_not_counted() -> None:
    """WebSocket/lifespan не инкрементят счётчик."""
    app = _BlockingApp()
    mw = ActiveRequestsMiddleware(app)

    # lifespan-скоуп — middleware должен проксировать без учёта.
    scope: Scope = {"type": "lifespan"}
    task = asyncio.create_task(mw(scope, _noop_receive, _noop_send))
    await app.entered.wait()

    # Счётчик не увеличен — мы пропустили non-HTTP.
    assert mw.active_count == 0

    app.release.set()
    await task


# ═══════════════════════════════════════════════════════════════════════════
# wait_for_zero
# ═══════════════════════════════════════════════════════════════════════════


async def test_wait_for_zero_returns_true_when_idle() -> None:
    """Если запросов нет — сразу True."""
    mw = ActiveRequestsMiddleware(_InstantApp())
    result = await mw.wait_for_zero(timeout=1.0)
    assert result is True


async def test_wait_for_zero_returns_true_after_completion() -> None:
    """Счётчик обнулился в пределах таймаута — True."""
    app = _BlockingApp()
    mw = ActiveRequestsMiddleware(app)

    task = asyncio.create_task(
        mw(_http_scope(), _noop_receive, _noop_send)
    )
    await app.entered.wait()
    assert mw.active_count == 1

    # Запускаем wait_for_zero параллельно.
    wait_task = asyncio.create_task(mw.wait_for_zero(timeout=2.0))

    # Через 200 мс отпускаем app — запрос завершится, wait_for_zero
    # должен вернуть True.
    await asyncio.sleep(0.2)
    app.release.set()

    result = await wait_task
    await task

    assert result is True
    assert mw.active_count == 0


async def test_wait_for_zero_returns_false_on_timeout() -> None:
    """Если запрос не завершился — False."""
    app = _BlockingApp()
    mw = ActiveRequestsMiddleware(app)

    task = asyncio.create_task(
        mw(_http_scope(), _noop_receive, _noop_send)
    )
    await app.entered.wait()

    # Таймаут 0.3 сек — app не отпущен, ждём False.
    result = await mw.wait_for_zero(timeout=0.3)

    assert result is False
    assert mw.active_count == 1

    # Убираем за собой.
    app.release.set()
    await task


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════


async def test_singleton_set_on_init() -> None:
    """После __init__ get_active_requests_middleware возвращает тот же инстанс."""
    reset_active_requests_middleware()
    mw = ActiveRequestsMiddleware(_InstantApp())

    assert get_active_requests_middleware() is mw


async def test_singleton_raises_before_init() -> None:
    """Без инициализации — RuntimeError."""
    reset_active_requests_middleware()

    with pytest.raises(RuntimeError, match="not initialized"):
        get_active_requests_middleware()


async def test_singleton_overwritten_by_new_instance() -> None:
    """Новый __init__ перезаписывает module-level ссылку."""
    mw1 = ActiveRequestsMiddleware(_InstantApp())
    assert get_active_requests_middleware() is mw1

    mw2 = ActiveRequestsMiddleware(_InstantApp())
    assert get_active_requests_middleware() is mw2
    assert get_active_requests_middleware() is not mw1