import pytest


@pytest.mark.asyncio
async def test_create_user(client, admin_token):
    resp = await client.post(
        "/api/users",
        json={"username": "bob", "password": "pass123", "role": "user"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"


@pytest.mark.asyncio
async def test_create_user_requires_admin(client, admin_token):
    resp = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    token = resp.json()["token"]
    resp = await client.post(
        "/api/users",
        json={"username": "bob", "password": "pass123", "role": "user"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
