import importlib

import pytest
from sqlalchemy import event, inspect, select, text

from app.models import Conversation, SchemaMigration


def service():
    return importlib.import_module("app.services.chat_scope_migration_service")


async def has_column(engine):
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync: "kb_scope" in {
            row["name"] for row in inspect(sync).get_columns("conversations")})


async def legacy(test_db):
    engine = test_db.kw["bind"]
    async with test_db() as db:
        db.add(Conversation(user_id=2, kb_id=1, title="保留会话", memory_thread_id="retained"))
        await db.commit()
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE conversations DROP COLUMN kb_scope"))
    return engine


async def test_scope_plan_is_read_only_and_missing_migration_blocks_startup(test_db):
    engine = await legacy(test_db)
    report = await service().plan_migration(engine)
    assert report["applied"] is False and report["conversations"] == 1
    assert not await has_column(engine)
    with pytest.raises(RuntimeError): await service().require_migration(engine)
    assert not await has_column(engine)


async def test_scope_migration_is_additive_and_idempotent(test_db):
    engine = await legacy(test_db)
    assert await service().apply_migration(engine)
    await service().require_migration(engine)
    async with test_db() as db:
        conv = await db.get(Conversation, 1)
        assert conv.title == "保留会话" and conv.memory_thread_id == "retained"
        db.add(Conversation(user_id=2, kb_id=None, kb_scope="[1]", memory_thread_id="new-thread"))
        await db.commit()
    assert not await service().apply_migration(engine)
    async with test_db() as db:
        assert (await db.get(Conversation, 2)).memory_thread_id == "new-thread"


async def test_scope_marker_failure_rolls_back_ddl(test_db):
    engine = await legacy(test_db)
    def fail(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().startswith("INSERT INTO schema_migrations"):
            raise RuntimeError("marker write failed")
    event.listen(engine.sync_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError): await service().apply_migration(engine)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail)
    assert not await has_column(engine)


async def test_scope_migration_requires_roles_initialization(test_db):
    engine = await legacy(test_db)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM schema_migrations"))
    with pytest.raises(RuntimeError): await service().apply_migration(engine)
    assert not await has_column(engine)
