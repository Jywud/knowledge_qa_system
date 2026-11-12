"""使用独立旧版 SQLite 数据库验证迁移，不接触业务数据库。"""
import hashlib
import importlib

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import User


@pytest_asyncio.fixture(autouse=True)
async def test_db():
    # 覆盖 conftest 的应用数据库：迁移必须从没有 RBAC 表的旧结构开始。
    yield


def service():
    assert importlib.util.find_spec("app.services.role_migration_service"), "缺少角色迁移服务"
    return importlib.import_module("app.services.role_migration_service")


@pytest_asyncio.fixture
async def legacy_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")

    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _record):
        connection.execute('PRAGMA foreign_keys=ON')

    async with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role VARCHAR(16) NOT NULL, password_hash TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE knowledge_bases (id INTEGER PRIMARY KEY, name TEXT, created_by INTEGER REFERENCES users(id))",
            "CREATE TABLE files (id INTEGER PRIMARY KEY, kb_id INTEGER REFERENCES knowledge_bases(id), filename TEXT, uploaded_by INTEGER REFERENCES users(id))",
            "CREATE TABLE chunks (id INTEGER PRIMARY KEY, file_id INTEGER REFERENCES files(id), content TEXT, embedding TEXT)",
            "CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), kb_id INTEGER REFERENCES knowledge_bases(id), title TEXT)",
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER REFERENCES conversations(id), content TEXT)",
        ):
            await conn.execute(text(ddl))
        await conn.execute(text("INSERT INTO users (id,username,role,password_hash) VALUES (1,'admin','admin','unchanged-hash'),(2,'alice','user','alice-hash')"))
        await conn.execute(text("INSERT INTO knowledge_bases VALUES (1,'资料库',2)"))
        await conn.execute(text("INSERT INTO files VALUES (1,1,'原文件.pdf',2)"))
        await conn.execute(text("INSERT INTO chunks VALUES (1,1,'保留正文','[0.1,0.2]')"))
        await conn.execute(text("INSERT INTO conversations VALUES (1,2,1,'旧会话')"))
        await conn.execute(text("INSERT INTO messages VALUES (1,1,'旧消息')"))
    (tmp_path / '原文件.pdf').write_bytes(b'original\x00file bytes')
    yield engine
    await engine.dispose()


async def fingerprint(engine):
    async with engine.connect() as conn:
        rows = [list((await conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))))
                for table in ('knowledge_bases', 'files', 'chunks')]
        rows.append((await conn.execute(text('SELECT id, username, password_hash, created_at FROM users ORDER BY id'))).all())
    return hashlib.sha256(repr(rows).encode()).hexdigest()


async def test_plan_is_read_only_without_new_tables(legacy_engine):
    module = service()
    before = await fingerprint(legacy_engine)
    plan = await module.plan_migration(legacy_engine)
    assert plan['users_by_role'] == {'admin': 1, 'user': 1}
    assert [plan[key] for key in ('knowledge_bases', 'files', 'chunks', 'legacy_conversations')] == [1, 1, 1, 1]
    assert before == await fingerprint(legacy_engine)
    async with legacy_engine.connect() as conn:
        assert 'roles' not in await conn.run_sync(lambda sync: inspect(sync).get_table_names())


async def test_migration_preserves_data_and_grants_only_admin(legacy_engine, tmp_path):
    module = service()
    before = await fingerprint(legacy_engine)
    original = (tmp_path / '原文件.pdf').read_bytes()
    assert await module.apply_migration(legacy_engine) is True
    assert before == await fingerprint(legacy_engine)
    assert (tmp_path / '原文件.pdf').read_bytes() == original
    async with legacy_engine.connect() as conn:
        assert (await conn.execute(text('SELECT name, system_key FROM roles'))).all() == [('系统管理员', 'system_admin')]
        assert (await conn.execute(text('SELECT user_id FROM user_roles'))).scalars().all() == [1]
        assert (await conn.execute(text('SELECT count(*) FROM role_knowledge_bases'))).scalar() == 0
        assert (await conn.execute(text('SELECT count(*) FROM conversations'))).scalar_one() == 0
        assert (await conn.execute(text('SELECT count(*) FROM messages'))).scalar_one() == 0
        columns = await conn.run_sync(lambda sync: {c['name'] for c in inspect(sync).get_columns('conversations')})
        assert {'memory_epoch', 'memory_thread_id'} <= columns
        assert 'role' not in await conn.run_sync(lambda sync: {c['name'] for c in inspect(sync).get_columns('users')})


async def test_rerun_does_not_regrant_or_reset_conversations(legacy_engine):
    module = service()
    await module.apply_migration(legacy_engine)
    async with legacy_engine.begin() as conn:
        await conn.execute(text('DELETE FROM user_roles'))
        await conn.execute(text("INSERT INTO conversations (id,user_id,kb_id,title,memory_epoch,rbac_ready,memory_thread_id) VALUES (2,2,1,'新会话',7,true,'completed-thread-pointer')"))
        await conn.execute(text("INSERT INTO messages VALUES (2,2,'新消息')"))
    assert await module.apply_migration(legacy_engine) is False
    assert (await module.plan_migration(legacy_engine))['legacy_conversations'] == 0
    async with legacy_engine.connect() as conn:
        assert (await conn.execute(text('SELECT count(*) FROM user_roles'))).scalar() == 0
        assert (await conn.execute(text('SELECT memory_epoch, rbac_ready FROM conversations'))).one() == (7, 1)
        assert (await conn.execute(text('SELECT memory_thread_id FROM conversations'))).scalar_one() == 'completed-thread-pointer'
        assert (await conn.execute(text('SELECT content FROM messages'))).scalar_one() == '新消息'


async def test_missing_admin_rolls_back_schema(legacy_engine):
    module = service()
    async with legacy_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET role='user'"))
    with pytest.raises(RuntimeError, match='管理员'):
        await module.apply_migration(legacy_engine)
    async with legacy_engine.connect() as conn:
        assert 'roles' not in await conn.run_sync(lambda sync: inspect(sync).get_table_names())
        assert 'rbac_ready' not in await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns('conversations')])


@pytest.mark.parametrize('failure_sql', ['CREATE TABLE user_roles', 'INSERT INTO roles', 'INSERT INTO schema_migrations'])
async def test_ddl_or_seed_failure_rolls_back_everything(legacy_engine, failure_sql):
    module = service()
    before = await fingerprint(legacy_engine)

    def fail_statement(_conn, _cursor, statement, _params, _context, _many):
        if failure_sql in ' '.join(statement.split()):
            raise RuntimeError('injected failure')

    event.listen(legacy_engine.sync_engine, 'before_cursor_execute', fail_statement)
    try:
        with pytest.raises(RuntimeError, match='injected failure'):
            await module.apply_migration(legacy_engine)
    finally:
        event.remove(legacy_engine.sync_engine, 'before_cursor_execute', fail_statement)
    assert before == await fingerprint(legacy_engine)
    async with legacy_engine.connect() as conn:
        assert 'roles' not in await conn.run_sync(lambda sync: inspect(sync).get_table_names())
        assert 'memory_epoch' not in await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns('conversations')])
        assert 'memory_thread_id' not in await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns('conversations')])
        assert 'role' in await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns('users')])
        assert (await conn.execute(text('SELECT count(*) FROM conversations'))).scalar_one() == 1
        assert (await conn.execute(text('SELECT count(*) FROM messages'))).scalar_one() == 1


async def test_require_migration_rejects_missing_table_and_marker(legacy_engine):
    module = service()
    with pytest.raises(RuntimeError, match='migrate_roles.py'):
        await module.require_migration(legacy_engine)
    async with legacy_engine.begin() as conn:
        await conn.execute(text('CREATE TABLE schema_migrations (version VARCHAR(64) PRIMARY KEY)'))
    with pytest.raises(RuntimeError, match='migrate_roles.py'):
        await module.require_migration(legacy_engine)
    await module.apply_migration(legacy_engine)
    await module.require_migration(legacy_engine)


async def test_fresh_install_without_legacy_role_column(legacy_engine):
    module = service()
    async with legacy_engine.begin() as conn:
        await conn.execute(text('ALTER TABLE users DROP COLUMN role'))
        for model in (module.Role, module.UserRole):
            await conn.run_sync(lambda sync, table=model.__table__: table.create(sync))
        await conn.execute(module.Role.__table__.insert().values(
            id=1, name='系统管理员', system_key='system_admin', description=''))
        await conn.execute(module.UserRole.__table__.insert().values(user_id=1, role_id=1))
    assert await module.apply_migration(legacy_engine) is True
    await module.require_migration(legacy_engine)
    async with legacy_engine.connect() as conn:
        assert (await conn.execute(text('SELECT count(*) FROM roles'))).scalar_one() == 1
        assert (await conn.execute(text('SELECT user_id FROM user_roles'))).scalars().all() == [1]


async def test_migrated_not_null_legacy_role_does_not_block_new_orm_user(legacy_engine):
    await service().apply_migration(legacy_engine)
    async with async_sessionmaker(legacy_engine, expire_on_commit=False)() as db:
        user = User(username='new_user', password_hash='new-hash')
        db.add(user)
        await db.commit()
        assert user.id is not None
        assert user.password_hash == 'new-hash'


async def test_old_conversation_no_longer_blocks_knowledge_base_deletion(legacy_engine):
    async with legacy_engine.begin() as conn:
        await conn.execute(text("INSERT INTO knowledge_bases VALUES (2,'无文件旧库',1)"))
        await conn.execute(text("INSERT INTO conversations VALUES (2,2,2,'阻塞删除的旧会话')"))
        await conn.execute(text("INSERT INTO messages VALUES (2,2,'旧回答')"))
    await service().apply_migration(legacy_engine)
    async with legacy_engine.begin() as conn:
        await conn.execute(text('DELETE FROM knowledge_bases WHERE id=2'))
        assert (await conn.execute(text('SELECT count(*) FROM knowledge_bases WHERE id=1'))).scalar_one() == 1


async def test_unknown_conversation_fk_refuses_cleanup_and_rolls_back(legacy_engine):
    async with legacy_engine.begin() as conn:
        await conn.execute(text('CREATE TABLE conversation_extras (id INTEGER PRIMARY KEY, conversation_id INTEGER REFERENCES conversations(id))'))
        await conn.execute(text('INSERT INTO conversation_extras VALUES (1,1)'))
    with pytest.raises(RuntimeError, match='外键'):
        await service().apply_migration(legacy_engine)
    async with legacy_engine.connect() as conn:
        assert (await conn.execute(text('SELECT count(*) FROM conversations'))).scalar_one() == 1
        assert (await conn.execute(text('SELECT count(*) FROM messages'))).scalar_one() == 1
        assert 'role' in await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns('users')])
