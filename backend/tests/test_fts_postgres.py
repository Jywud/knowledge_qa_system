"""显式启用的 PostgreSQL zhparser 全文检索验证；随机 schema 隔离，不污染开发数据。"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import hash_password
from app.database import Base, engine
from app.models import (Chunk, FileRecord, KnowledgeBase, Role, RoleKnowledgeBase,
                        User, UserRole)
from app.services import retrieval_service
from app.services.fts_service import ensure_fts

pytestmark = [
    pytest.mark.skipif(os.getenv("FTS_POSTGRES_TESTS") != "1",
                       reason="显式启用 PostgreSQL 全文检索验证"),
    pytest.mark.fts,
]


@pytest.fixture(autouse=True)
async def test_db(monkeypatch):
    """遮蔽 conftest 的 SQLite fixture；随机 schema 隔离，全程使用本 fixture 的隔离引擎。"""
    schema = "fts_test_" + uuid4().hex
    isolated = create_async_engine(
        engine.url, connect_args={"server_settings": {"search_path": f"{schema},public"}})
    factory = async_sessionmaker(isolated, expire_on_commit=False)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    try:
        async with isolated.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            metadata = MetaData(schema=schema)
            for table in Base.metadata.sorted_tables:
                table.to_metadata(metadata)
            await conn.run_sync(metadata.create_all)
            await ensure_fts(conn)
        async with factory() as db:
            db.add(User(id=1, username="admin", password_hash=hash_password("x")))
            db.add(User(id=2, username="alice", password_hash=hash_password("x")))
            db.add(Role(id=2, name="测试角色"))
            await db.flush()
            db.add(KnowledgeBase(id=1, name="已授权库", created_by=1))
            db.add(KnowledgeBase(id=2, name="未授权库", created_by=1))
            await db.flush()
            db.add(UserRole(user_id=2, role_id=2))
            db.add(RoleKnowledgeBase(role_id=2, kb_id=1))
            await db.flush()
            for kb_id, content in [
                (1, "企业知识库支持中文全文检索与权限过滤"),
                (1, "向量检索与关键词检索通过RRF融合排序"),
                (2, "机密的内部薪酬数据绝不能泄露"),
            ]:
                file = FileRecord(kb_id=kb_id, filename=f"{kb_id}.md", file_type="md", uploaded_by=1)
                db.add(file)
                await db.flush()
                db.add(Chunk(file_id=file.id, chunk_index=0, content=content))
            await db.commit()
        yield factory
    finally:
        async with isolated.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await isolated.dispose()


async def test_fts_finds_word_level_matches(test_db):
    docs = await retrieval_service._fts_search("全文检索", None, 5, user_id=2, kb_ids=[1, 2])
    assert docs and docs[0].metadata["kb_id"] == "1"
    assert docs[0].page_content.startswith("企业知识库")
    assert docs[0].metadata["file_version"] == 1


async def test_fts_never_reads_ungranted_library(test_db):
    assert await retrieval_service._fts_search("内部薪酬", None, 5, user_id=2, kb_ids=[1, 2]) == []
    assert await retrieval_service._fts_search("内部薪酬", 2, 5, user_id=2) == []


async def test_fts_or_fallback_recalls_partial_matches(test_db):
    docs = await retrieval_service._fts_search("向量检索 薪酬 报销", None, 5, user_id=2, kb_ids=[1])
    assert docs and docs[0].metadata["kb_id"] == "1"


async def test_hybrid_degrades_to_fts_when_embedding_fails(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    docs = await retrieval_service.hybrid_search("全文检索", None, 5, user_id=2, kb_ids=[1, 2])
    assert docs and docs[0].metadata["kb_id"] == "1"


async def test_fts_chunk_keys_stay_stable(test_db):
    docs = await retrieval_service._fts_search("中文全文检索", None, 10, user_id=2, kb_ids=[1])
    keys = {(d.metadata["file_id"], d.metadata["chunk_index"]) for d in docs}
    assert len(keys) == len(docs) >= 1
