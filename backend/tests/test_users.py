import pytest
from sqlalchemy import select

from app.models import User


@pytest.mark.asyncio
async def test_create_user(client, admin_token):
    resp = await client.post(
        "/api/users",
        json={"username": "bob", "password": "pass123", "role_ids": [2]},
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
        json={"username": "bob", "password": "pass123", "role_ids": [2]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("username", ["", "   ", "x" * 65])
async def test_create_user_rejects_invalid_username(client, admin_token, test_db, username):
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": username, "password": "valid123", "role_ids": [2]})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    async with test_db() as db:
        assert len((await db.scalars(select(User))).all()) == 2


async def test_create_user_normalizes_username_before_duplicate_check(client, admin_token):
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": "  alice  ", "password": "valid123", "role_ids": [2]})
    assert response.status_code == 400
    assert "已存在" in response.json()["detail"]


@pytest.mark.parametrize("username,password", [(" 大鱼 ", "123456"), ("x" * 64, "p" * 128)])
async def test_create_user_accepts_policy_boundaries(client, admin_token, username, password):
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": username, "password": password, "role_ids": [2]})
    assert response.status_code == 200
    assert response.json()["username"] == username.strip()


@pytest.mark.parametrize("password", ["", "12345", " " * 6, "p" * 129])
@pytest.mark.parametrize("operation", ["create", "reset"])
async def test_admin_password_writes_reject_invalid_values(
    client, admin_token, test_db, password, operation,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    if operation == "create":
        response = await client.post("/api/users", headers=headers,
                                     json={"username": "newuser", "password": password, "role_ids": [2]})
    else:
        response = await client.put("/api/users/2/password", headers=headers, json={"password": password, "role_ids": [2]})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    async with test_db() as db:
        assert len((await db.scalars(select(User))).all()) == 2
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    assert login.status_code == 200
