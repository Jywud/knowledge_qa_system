import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.auth import hash_password
from app.routers.auth import _login_attempts
from app.models import KnowledgeBase, SystemSetting, User
from app.main import app


@pytest.fixture(autouse=True)
async def test_db(tmp_path, monkeypatch):
    _login_attempts.clear()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.database.SessionLocal", session_factory)
    monkeypatch.setattr("app.routers.chat.SessionLocal", session_factory)
    monkeypatch.setattr("app.config.settings.upload_dir", str(tmp_path))

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        session.add(SystemSetting(id=1))
        session.add(User(username="admin", role="admin", password_hash=hash_password("123456")))
        session.add(User(username="alice", role="user", password_hash=hash_password("pass1")))
        await session.commit()
        session.add(KnowledgeBase(name="测试库", description="", created_by=1))
        await session.commit()

    try:
        yield session_factory
    finally:
        app.dependency_overrides.pop(get_db)
        await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_token(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    return resp.json()["token"]
