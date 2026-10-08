"""In-memory pub/sub для WebSocket-канала соревнования.

На MVP подходит один backend-процесс. Если backend будет масштабироваться
на несколько воркеров/реплик — заменить на Redis pub/sub.
"""
import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class CompetitionStreamHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, slug: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers[slug].add(ws)

    async def unsubscribe(self, slug: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers[slug].discard(ws)

    async def broadcast(self, slug: str, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(slug, set()))
        dead: list[WebSocket] = []
        for ws in subscribers:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers[slug].discard(ws)


hub = CompetitionStreamHub()


def publish_sync(channel: str, event: dict[str, Any]) -> None:
    """Синхронный helper для вызова из обычных endpoints.

    channel — уже готовый ключ, например `comp:demo-2026` или `user:42`.
    Если нет работающего loop'а — пропускаем (WebSocket-канал не активен).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(hub.broadcast(channel, event))