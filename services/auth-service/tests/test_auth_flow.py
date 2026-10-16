"""Happy-path: register → login → me → refresh → logout."""

from httpx import AsyncClient

VALID_PASSWORD = "correct horse battery staple nist"


async def test_full_auth_flow(client: AsyncClient) -> None:
    # ── 1. Register ─────────────────────────────────────────────────────────
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "username": "alice",
            "password": VALID_PASSWORD,
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["email"] == "alice@example.com"
    assert user["username"] == "alice"
    assert user["status"] == "pending_verification"
    assert user["id"] > 0

    # ── 2. Login ────────────────────────────────────────────────────────────
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] > 0
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["session_id"]

    # ── 3. Me ───────────────────────────────────────────────────────────────
    r = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == "alice@example.com"
    # После первого логина статус переходит из PENDING в ACTIVE
    assert me["status"] == "active"

    # ── 4. Refresh ──────────────────────────────────────────────────────────
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r.status_code == 200, r.text
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # ВАЖНО: session_id сохраняется при ротации
    assert new_tokens["session_id"] == tokens["session_id"]

    # ── 5. Logout ───────────────────────────────────────────────────────────
    r = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        json={"refresh_token": new_tokens["refresh_token"], "all_sessions": False},
    )
    assert r.status_code == 200, r.text
    assert "Logged out" in r.json()["message"]

    # ── 6. После logout refresh-токен не работает ───────────────────────────
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert r.status_code == 401