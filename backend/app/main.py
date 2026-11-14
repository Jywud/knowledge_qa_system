from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from app import models  # noqa: F401 确保模型注册
from app.config import settings
from app.database import Base, engine
from app.auth import hash_password
from app.routers import auth, chat, chunks, files, roles, users
from app.routers import knowledge_bases
from app.routers import settings as settings_router
from app.database import SessionLocal
from app.services.rag_service import build_graph
from app.services.document_service import reindex_missing_embeddings

logger = logging.getLogger(__name__)


async def _reindex_on_startup() -> None:
    try:
        async with SessionLocal() as db:
            await reindex_missing_embeddings(db)
    except Exception:
        logger.exception("启动向量补齐失败，继续启动；缺失向量待服务恢复后重新处理")


async def _initialize_database() -> None:
    from sqlalchemy import inspect
    from app.services.role_migration_service import MIGRATION_VERSION, require_migration
    from app.services.chat_scope_migration_service import MIGRATION_VERSION as SCOPE_VERSION, require_migration as require_scope_migration

    async with engine.connect() as conn:
        fresh = not await conn.run_sync(lambda sync: inspect(sync).has_table("users"))
    if not fresh:
        await require_migration(engine)
        await require_scope_migration(engine)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        try:
            from app.services.fts_service import ensure_fts
            async with conn.begin_nested():
                await ensure_fts(conn)
        except Exception:
            logger.exception("zhparser 全文检索初始化失败，关键词检索将降级为纯向量结果；"
                             "生产部署请使用自建 PostgreSQL 镜像（backend/docker/Dockerfile.pgvector）")
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        ))
        if fresh:
            role_id = (await conn.execute(models.Role.__table__.insert().values(
                name="系统管理员", description="系统管理与全部知识库访问",
                system_key="system_admin").returning(models.Role.id))).scalar_one()
            admin_id = (await conn.execute(models.User.__table__.insert().values(
                username="admin", password_hash=hash_password("123456"))
                .returning(models.User.id))).scalar_one()
            await conn.execute(models.UserRole.__table__.insert().values(user_id=admin_id, role_id=role_id))
            await conn.execute(models.SchemaMigration.__table__.insert().values(version=MIGRATION_VERSION))
            await conn.execute(models.SchemaMigration.__table__.insert().values(version=SCOPE_VERSION))
        await conn.execute(text(
            "UPDATE files SET status='failed', status_message='服务重启导致处理中断，请重新上传' "
            "WHERE status='processing'"
        ))
        await conn.execute(text(
            "INSERT INTO system_settings (id, chunk_size, chunk_overlap, top_k) "
            "SELECT 1, 800, 100, 5 WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE id=1)"
        ))
        kb = (await conn.execute(text("SELECT id FROM knowledge_bases LIMIT 1"))).first()
        if kb is None:
            admin_id = (await conn.execute(text(
                "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                "WHERE r.system_key='system_admin' ORDER BY ur.user_id LIMIT 1"
            ))).scalar_one()
            await conn.execute(models.KnowledgeBase.__table__.insert().values(
                name="默认知识库", description="系统自动创建的默认知识库", created_by=admin_id))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _initialize_database()
    await _reindex_on_startup()
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="企业知识库问答系统", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(roles.router)
app.include_router(auth.router)
app.include_router(knowledge_bases.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(chunks.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
