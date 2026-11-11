import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.config import settings


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert set(data["user"]) == {"id", "username", "role"}


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


async def test_login_failures_do_not_lock_other_source(client):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    for _ in range(5):
        await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    async with AsyncClient(transport=ASGITransport(app=app, client=("203.0.113.8", 1234)), base_url="http://test") as other:
        response = await other.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert response.status_code == 200


async def test_successful_login_does_not_clear_shared_failure_budget(client):
    for _ in range(4):
        await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    success = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    assert success.status_code == 200
    await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    blocked = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert blocked.status_code == 429


async def test_rotating_username_or_forwarded_header_cannot_bypass_source_limit(client):
    for i in range(5):
        await client.post("/api/auth/login", json={"username": f"missing{i}", "password": "wrong"})
    response = await client.post("/api/auth/login", headers={"X-Forwarded-For": "203.0.113.9"},
                                 json={"username": "admin", "password": "123456"})
    assert response.status_code == 429


async def test_trusted_proxy_keeps_clients_separate_and_untrusted_peer_cannot_spoof():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from app.routers import auth
    from fastapi import Request
    probe = FastAPI()
    @probe.get("/")
    async def endpoint(request: Request):
        source = request.client.host
        auth._check_lock(source)
        auth._record_failure(source)
        return {"source": source}
    wrapped = ProxyHeadersMiddleware(probe, trusted_hosts=["10.0.0.2"])
    async with AsyncClient(transport=ASGITransport(app=wrapped, client=("10.0.0.2", 1234)), base_url="http://test") as proxy:
        for _ in range(5):
            assert (await proxy.get("/", headers={"X-Forwarded-For":"203.0.113.1"})).status_code == 200
        assert (await proxy.get("/", headers={"X-Forwarded-For":"203.0.113.1"})).status_code == 429
        other = await proxy.get("/", headers={"X-Forwarded-For":"203.0.113.2"})
        assert other.status_code == 200 and other.json()["source"] == "203.0.113.2"
    async with AsyncClient(transport=ASGITransport(app=wrapped, client=("203.0.113.3", 1234)), base_url="http://test") as direct:
        for i in range(5):
            result = await direct.get("/", headers={"X-Forwarded-For":f"192.0.2.{i}"})
            assert result.json()["source"] == "203.0.113.3"
        assert (await direct.get("/", headers={"X-Forwarded-For":"192.0.2.100"})).status_code == 429


def test_login_rate_records_expire_and_have_capacity(monkeypatch):
    from app.routers import auth
    from datetime import datetime as real_datetime
    clock = [real_datetime.now(timezone.utc)]
    class Clock:
        @staticmethod
        def now(tz):
            return clock[0]
    monkeypatch.setattr(auth, "datetime", Clock)
    for i in range(5000):
        auth._record_failure(f"source-{i}")
    assert len(auth._login_attempts) <= 4096
    clock[0] += timedelta(minutes=settings.login_lock_minutes + 1)
    auth._check_lock("new-source")
    assert not auth._login_attempts


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


async def test_change_password_revokes_old_token(client):
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    response = await client.put("/api/auth/password", headers=headers,
                                json={"old_password": "pass1", "new_password": "newpass1"})
    assert response.status_code == 200
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
    new_login = await client.post("/api/auth/login", json={"username": "alice", "password": "newpass1"})
    new_headers = {"Authorization": f"Bearer {new_login.json()['token']}"}
    assert (await client.get("/api/auth/me", headers=new_headers)).status_code == 200


@pytest.mark.parametrize("new_password", ["newpass1", "oldpass1"])
async def test_admin_reset_revokes_old_token_only_for_target(client, admin_token, new_password):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    # 同明文重置仍需满足新密码规则；旧短密码登录由其余用例保留覆盖。
    seeded = await client.put("/api/users/2/password", headers=admin_headers, json={"password": "oldpass1"})
    assert seeded.status_code == 200
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "oldpass1"})
    old_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    response = await client.put("/api/users/2/password", headers=admin_headers, json={"password": new_password})
    assert response.status_code == 200
    assert (await client.get("/api/auth/me", headers=old_headers)).status_code == 401
    assert (await client.get("/api/auth/me", headers=admin_headers)).status_code == 200
    new_login = await client.post("/api/auth/login", json={"username": "alice", "password": new_password})
    new_headers = {"Authorization": f"Bearer {new_login.json()['token']}"}
    assert (await client.get("/api/auth/me", headers=new_headers)).status_code == 200


@pytest.mark.parametrize("extra", [{}, {"pwd_ver": None}, {"pwd_ver": ["bad"]}, {"pwd_ver": "非ASCII版本"}, {"pwd_ver": "\ud800"}, {"pwd_ver": "bad", "sub": "invalid"}])
async def test_legacy_or_malformed_token_is_rejected(client, extra):
    payload = {"sub": "2", "exp": datetime.now(timezone.utc) + timedelta(hours=1), **extra}
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize("new_password", ["", "12345", " " * 6, "p" * 129])
async def test_invalid_personal_password_change_keeps_credentials(client, new_password):
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    response = await client.put("/api/auth/password", headers=headers,
                                json={"old_password": "pass1", "new_password": new_password})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
    assert (await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})).status_code == 200
