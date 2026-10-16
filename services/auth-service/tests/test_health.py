"""Health-check endpoints."""

from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    """Liveness всегда 200, если приложение отвечает."""
    r = await client.get("/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "version" in body


async def test_readiness_healthy(client: AsyncClient) -> None:
    """Readiness 200, когда БД доступна."""
    r = await client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["checks"]["database"]["status"] == "ok"


async def test_correlation_id_generated(client: AsyncClient) -> None:
    """Если X-Correlation-ID не передан, генерируется и возвращается."""
    r = await client.get("/health/live")
    assert "x-correlation-id" in {k.lower() for k in r.headers}


async def test_correlation_id_echoed(client: AsyncClient) -> None:
    """Если клиент передал X-Correlation-ID, он возвращается как есть."""
    cid = "test-trace-12345678"
    r = await client.get("/health/live", headers={"X-Correlation-ID": cid})
    assert r.headers.get("x-correlation-id") == cid