"""显式、事务化的角色初始化；不迁移旧共享授权或会话记忆。"""
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.models import Role, RoleKnowledgeBase, SchemaMigration, UserRole

MIGRATION_VERSION = "roles_v1"
_MIGRATION_HELP = "角色权限尚未初始化，请停止后端后运行 backend/scripts/migrate_roles.py --plan，再运行 --apply。"


async def _tables(conn: AsyncConnection) -> set[str]:
    return set(await conn.run_sync(lambda sync: inspect(sync).get_table_names()))


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    return set(await conn.run_sync(lambda sync: [c['name'] for c in inspect(sync).get_columns(table)]))


async def _applied(conn: AsyncConnection, tables: set[str]) -> bool:
    if 'schema_migrations' not in tables:
        return False
    return (await conn.execute(select(SchemaMigration.version).where(
        SchemaMigration.version == MIGRATION_VERSION))).scalar_one_or_none() is not None


async def _check_conversation_dependencies(conn: AsyncConnection, tables: set[str]) -> None:
    """只清理已知会话链，未知外键依赖应明确失败，避免级联误删业务数据。"""
    def check(sync):
        inspector = inspect(sync)
        for table in sorted(tables):
            for foreign_key in inspector.get_foreign_keys(table):
                referred = foreign_key['referred_table']
                if referred not in {'messages', 'conversations'}:
                    continue
                if table == 'messages' and referred == 'conversations':
                    continue
                raise RuntimeError('旧会话存在未支持的外键依赖，迁移已停止，请先核实数据库结构。')
    await conn.run_sync(check)


async def plan_migration(engine: AsyncEngine) -> dict[str, object]:
    """只读预检，仅返回计数；支持未包含新列/新表的旧数据库。"""
    async with engine.connect() as conn:
        tables = await _tables(conn)
        roles = {}
        if 'users' in tables:
            if 'role' in await _columns(conn, 'users'):
                roles = dict((await conn.execute(text(
                    'SELECT role, count(*) FROM users GROUP BY role ORDER BY role'
                ))).all())
            else:
                roles = {'未分类': (await conn.execute(text('SELECT count(*) FROM users'))).scalar_one()}
        plan: dict[str, object] = {'users_by_role': roles}
        for table in ('knowledge_bases', 'files', 'chunks'):
            plan[table] = (await conn.execute(text(f'SELECT count(*) FROM {table}'))).scalar_one() if table in tables else 0
        if 'conversations' not in tables or await _applied(conn, tables):
            plan['legacy_conversations'] = 0
        else:
            plan['legacy_conversations'] = (await conn.execute(text('SELECT count(*) FROM conversations'))).scalar_one()
        return plan


async def require_migration(engine: AsyncEngine) -> None:
    """旧数据库启动前检查标记，不创建表，不自动补授任何权限。"""
    async with engine.connect() as conn:
        if not await _applied(conn, await _tables(conn)):
            raise RuntimeError(_MIGRATION_HELP)


async def apply_migration(engine: AsyncEngine) -> bool:
    """一次事务完成 DDL、管理员映射和标记；已迁移返回 False。"""
    async with engine.begin() as conn:
        if conn.dialect.name == 'postgresql':
            # 数据库内固定锁，重复/并发运行也只初始化一次。
            await conn.execute(text('SELECT pg_advisory_xact_lock(7262656301)'))
        elif conn.dialect.name == 'sqlite':
            # sqlite3 legacy transaction 模式不会为 DDL 自动 BEGIN。
            await conn.execute(text('BEGIN IMMEDIATE'))
        else:
            raise RuntimeError('角色迁移仅支持 PostgreSQL 和 SQLite。')
        tables = await _tables(conn)
        if await _applied(conn, tables):
            return False
        if 'users' not in tables:
            raise RuntimeError('尚无用户表，请先通过全新安装流程创建系统管理员。')

        for model in (Role, UserRole, RoleKnowledgeBase, SchemaMigration):
            await conn.run_sync(lambda sync, table=model.__table__: table.create(sync, checkfirst=True))

        columns = await _columns(conn, 'users')
        admin_ids = set()
        if 'role' in columns:
            admin_ids.update((await conn.execute(text("SELECT id FROM users WHERE role='admin'"))).scalars())
        # 全新安装不含旧 role 列，由安装入口显式创建系统管理员关联。
        admin_ids.update((await conn.execute(text(
            "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "JOIN users u ON u.id=ur.user_id WHERE r.system_key='system_admin'"
        ))).scalars())
        if not admin_ids:
            raise RuntimeError('未找到系统管理员，迁移已回滚；请先核实管理员账号。')

        role_id = (await conn.execute(select(Role.id).where(Role.system_key == 'system_admin'))).scalar_one_or_none()
        if role_id is None:
            role_id = (await conn.execute(Role.__table__.insert().values(
                name='系统管理员', description='系统管理与全部知识库访问', system_key='system_admin'
            ).returning(Role.id))).scalar_one()
        existing_ids = set((await conn.execute(select(UserRole.user_id).where(UserRole.role_id == role_id))).scalars())
        for user_id in sorted(admin_ids - existing_ids):
            await conn.execute(UserRole.__table__.insert().values(user_id=user_id, role_id=role_id))

        await _check_conversation_dependencies(conn, tables)
        # 旧列通常 NOT NULL 且没有数据库默认值；保留会阻塞新 ORM 新建用户。
        if 'role' in columns:
            await conn.execute(text('ALTER TABLE users DROP COLUMN role'))
        if 'messages' in tables:
            await conn.execute(text('DELETE FROM messages'))
        if 'conversations' in tables:
            # 旧会话不迁移，不留下阻塞知识库删除的外键引用。
            await conn.execute(text('DELETE FROM conversations'))
            conv_columns = await _columns(conn, 'conversations')
            if 'memory_epoch' not in conv_columns:
                await conn.execute(text('ALTER TABLE conversations ADD COLUMN memory_epoch INTEGER NOT NULL DEFAULT 1'))
            if 'rbac_ready' not in conv_columns:
                await conn.execute(text('ALTER TABLE conversations ADD COLUMN rbac_ready BOOLEAN NOT NULL DEFAULT false'))
            if 'memory_thread_id' not in conv_columns:
                await conn.execute(text('ALTER TABLE conversations ADD COLUMN memory_thread_id VARCHAR(255)'))
        await conn.execute(SchemaMigration.__table__.insert().values(version=MIGRATION_VERSION))
        return True
