import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.auth import hash_password
from app.routers.auth import _login_attempts
from app.models import KnowledgeBase, Role, RoleKnowledgeBase, SchemaMigration, SystemSetting, User, UserRole
from app.main import app


@pytest.fixture(autouse=True)
async def test_db(tmp_path, monkeypatch):
    _login_attempts.clear()
    # 流生成与撤权检查使用独立事务，不能共用内存库的单个连接。
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", echo=False)

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
        session.add(User(username="admin", password_hash=hash_password("123456")))
        session.add(User(username="alice", password_hash=hash_password("pass1")))
        session.add(Role(id=1, name="系统管理员", system_key="system_admin"))
        session.add(Role(id=2, name="测试角色"))
        session.add(SchemaMigration(version="roles_v1"))
        await session.commit()
        session.add(KnowledgeBase(name="测试库", description="", created_by=1))
        await session.commit()
        session.add_all([UserRole(user_id=1, role_id=1), UserRole(user_id=2, role_id=2),
                         RoleKnowledgeBase(role_id=2, kb_id=1)])
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
