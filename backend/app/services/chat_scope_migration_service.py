"""仅增加跨库会话范围字段，不改知识库内容或旧会话记忆。"""
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.models import SchemaMigration

MIGRATION_VERSION = "chat_scope_v1"
_HELP = "跨库会话范围尚未初始化，请停止后端，备份后执行 backend/scripts/migrate_chat_scope.py --plan / --apply。"


async def _versions(conn: AsyncConnection) -> set[str]:
    tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
    if "schema_migrations" not in tables:
        return set()
    return set((await conn.scalars(select(SchemaMigration.version))).all())


async def plan_migration(engine: AsyncEngine) -> dict:
    async with engine.connect() as conn:
        versions = await _versions(conn)
        tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
        count = await conn.scalar(text("SELECT count(*) FROM conversations")) if "conversations" in tables else 0
        return {"applied": MIGRATION_VERSION in versions, "roles_ready": "roles_v1" in versions,
                "conversations": count, "adds": "conversations.kb_scope TEXT NULL"}


async def require_migration(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        if MIGRATION_VERSION not in await _versions(conn):
            raise RuntimeError(_HELP)


async def apply_migration(engine: AsyncEngine) -> bool:
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(7262656301)"))
        elif conn.dialect.name == "sqlite":
            await conn.execute(text("BEGIN IMMEDIATE"))
        else:
            raise RuntimeError("跨库范围初始化仅支持 PostgreSQL 与 SQLite")
        versions = await _versions(conn)
        if "roles_v1" not in versions:
            raise RuntimeError("请先完成角色权限初始化，再增加跨库会话范围")
        if MIGRATION_VERSION in versions:
            return False
        columns = await conn.run_sync(lambda sync: {
            row["name"] for row in inspect(sync).get_columns("conversations")})
        if "kb_scope" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN kb_scope TEXT NULL"))
        await conn.execute(SchemaMigration.__table__.insert().values(version=MIGRATION_VERSION))
        return True
