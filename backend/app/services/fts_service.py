"""zhparser 中文全文检索的幂等初始化：扩展、检索配置、数据库级分词参数与表达式 GIN 索引。

调整分词参数（下方 ALTER DATABASE 两项）或检索配置映射后，
必须重建索引：REINDEX INDEX idx_chunks_content_fts，否则索引与查询的分词口径不一致。
若库中已存在同名 `zh` 配置，将按现状使用，不校验其分词映射。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

FTS_CONFIG_NAME = "zh"
FTS_INDEX_NAME = "idx_chunks_content_fts"


def _sql_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def ensure_fts(conn: AsyncConnection) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS zhparser"))
    exists = (await conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = :name)"),
        {"name": FTS_CONFIG_NAME})).scalar()
    if not exists:
        await conn.execute(text(
            f"CREATE TEXT SEARCH CONFIGURATION {FTS_CONFIG_NAME} (PARSER = zhparser)"))
        await conn.execute(text(
            f"ALTER TEXT SEARCH CONFIGURATION {FTS_CONFIG_NAME} "
            "ADD MAPPING FOR n,v,a,i,e,l WITH simple"))
    db_name = (await conn.execute(text("SELECT current_database()"))).scalar()
    await conn.execute(text(
        f"ALTER DATABASE {_sql_ident(db_name)} SET zhparser.punctuation_ignore = 'on'"))
    await conn.execute(text(
        f"ALTER DATABASE {_sql_ident(db_name)} SET zhparser.multi_short = 'on'"))
    await conn.execute(text("SET zhparser.punctuation_ignore = 'on'"))
    await conn.execute(text("SET zhparser.multi_short = 'on'"))
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS {FTS_INDEX_NAME} "
        "ON chunks USING GIN (to_tsvector('zh'::regconfig, content))"))
