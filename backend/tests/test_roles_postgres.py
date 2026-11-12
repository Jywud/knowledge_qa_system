"""显式启用的 PostgreSQL 隔离验证；仅创建和删除随机测试 schema。"""
import asyncio
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import create_token, hash_password
from app.database import Base, engine, get_db
from app.main import app
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, Role, User, UserRole
from app.services.role_migration_service import apply_migration

pytestmark = pytest.mark.skipif(os.getenv("RBAC_POSTGRES_TESTS") != "1", reason="显式启用 PostgreSQL 隔离验证")


@pytest.fixture(autouse=True)
async def test_db():
    yield  # 不使用普通 SQLite fixture。


async def test_postgres_migration_acl_and_concurrent_last_admin(monkeypatch):
    schema = "rbac_test_" + uuid4().hex
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": f"{schema},public"}})
    factory = async_sessionmaker(isolated, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    original_override = app.dependency_overrides.get(get_db)
    try:
        metadata = MetaData(schema=schema)
        for table in Base.metadata.sorted_tables:
            table.to_metadata(metadata)
        async with isolated.begin() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL"))
            await conn.execute(text("ALTER TABLE conversations DROP COLUMN memory_epoch, DROP COLUMN memory_thread_id, DROP COLUMN rbac_ready, DROP COLUMN kb_scope"))
            for name, role in [("a1", "admin"), ("a2", "admin"), ("employee", "user")]:
                await conn.execute(text("INSERT INTO users(username,password_hash,role) VALUES (:name,:password,:role)"),
                                   {"name": name, "password": hash_password("test-only-password"), "role": role})
            await conn.execute(text("INSERT INTO knowledge_bases(name,description,created_by) VALUES ('allowed','',1),('secret','',1)"))
            await conn.execute(text("INSERT INTO conversations(user_id,kb_id,title) VALUES (3,1,'discard old')"))
            await conn.execute(text("INSERT INTO messages(conversation_id,role,content) VALUES (1,'user','old context')"))
        assert await apply_migration(isolated)
        assert not await apply_migration(isolated)
        from app.services.chat_scope_migration_service import apply_migration as apply_scope
        assert await apply_scope(isolated)
        assert not await apply_scope(isolated)
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Conversation)) == 0
            new_user = User(username="new-user", password_hash=hash_password("test-only-password"))
            db.add(new_user)
            for kb_id, name in [(1, "allowed.md"), (2, "secret.md")]:
                file = FileRecord(kb_id=kb_id, filename=name, file_type="md", uploaded_by=1)
                db.add(file)
                await db.flush()
                db.add(Chunk(file_id=file.id, chunk_index=0, content=name,
                             embedding=[1.0] + [0.0] * 1023))
            await db.commit()
            admin1, admin2, employee = [await db.get(User, uid) for uid in (1, 2, 3)]
            tokens = [create_token(user) for user in (admin1, admin2, employee)]

        async def override_db():
            async with factory() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        monkeypatch.setattr("app.database.SessionLocal", factory)
        monkeypatch.setattr("app.routers.chat.SessionLocal", factory)
        headers = [{"Authorization": f"Bearer {token}"} for token in tokens]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated") as client:
            response = await client.post("/api/roles", headers=headers[0], json={"name": "scope", "kb_ids": [1]})
            assert response.status_code == 200, response.text
            role_id = response.json()["id"]
            assert (await client.put("/api/users/3/roles", headers=headers[0], json={"role_ids": [role_id]})).status_code == 200
            assert [row["id"] for row in (await client.get("/api/knowledge-bases", headers=headers[2])).json()] == [1]
            from app.services.retrieval_service import _vector_search
            docs = await _vector_search([1.0] + [0.0] * 1023, 1, 10, user_id=3)
            assert docs and {doc.metadata["kb_id"] for doc in docs} == {"1"}
            assert await _vector_search([1.0] + [0.0] * 1023, 2, 10, user_id=3) == []
            all_docs = await _vector_search([1.0] + [0.0] * 1023, None, 10, user_id=3, kb_ids=[1, 2])
            assert {doc.metadata["kb_id"] for doc in all_docs} == {"1"}
            assert await _vector_search([1.0] + [0.0] * 1023, None, 10, user_id=3, kb_ids=[2]) == []
            results = await asyncio.gather(*[
                client.put(f"/api/users/{uid}/roles", headers=headers[uid - 1], json={"role_ids": [role_id]})
                for uid in (1, 2)
            ])
            assert sorted(r.status_code for r in results) in ([200, 403], [200, 409])
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(UserRole).join(Role).where(Role.system_key == "system_admin")) == 1
            assert await db.scalar(select(func.count()).select_from(KnowledgeBase)) == 2
            assert await db.scalar(select(func.count()).select_from(Chunk)) == 2
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
