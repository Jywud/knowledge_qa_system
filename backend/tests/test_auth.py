import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_lockout(client):
    for _ in range(5):
        resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 429
    assert "分钟" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_requires_old_password(client):
    resp = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    token = resp.json()["token"]
    resp = await client.put(
        "/api/auth/password",
        json={"old_password": "wrong", "new_password": "newpass1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_updates_login_credential(client):
    resp = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    token = resp.json()["token"]
    resp = await client.put(
        "/api/auth/password",
        json={"old_password": "pass1", "new_password": "newpass1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    old_login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    new_login = await client.post("/api/auth/login", json={"username": "alice", "password": "newpass1"})
    assert old_login.status_code == 400
    assert new_login.status_code == 200
