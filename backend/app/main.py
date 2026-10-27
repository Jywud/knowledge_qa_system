from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from app import models  # noqa: F401 确保模型注册
from app.config import settings
from app.database import Base, engine
from app.auth import hash_password
from app.routers import auth, chat, files, users
from app.routers import knowledge_bases
from app.routers import settings as settings_router
from app.database import SessionLocal
from app.services.rag_service import build_graph
from app.services.document_service import reindex_missing_kb


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) DEFAULT 'user'")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)")
        )
        await conn.execute(text("ALTER TABLE files ADD COLUMN IF NOT EXISTS kb_id INTEGER"))
        await conn.execute(
            text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kb_id INTEGER")
        )
        await conn.execute(
            text(
                "INSERT INTO system_settings (id, chunk_size, chunk_overlap, top_k) "
                "SELECT 1, 800, 100, 5 WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE id = 1)"
            )
        )
        seeded = await conn.execute(text("SELECT 1 FROM users WHERE username='admin'"))
        if seeded.first() is None:
            await conn.execute(
                text(
                    "INSERT INTO users (username, role, password_hash) "
                    "VALUES ('admin', 'admin', :hash)"
                ),
                {"hash": hash_password("123456")},
            )
        kb_row = await conn.execute(text("SELECT id FROM knowledge_bases ORDER BY id LIMIT 1"))
        kb = kb_row.first()
        if kb is None:
            admin_id = (
                await conn.execute(text("SELECT id FROM users WHERE username='admin'"))
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO knowledge_bases (name, description, created_by) "
                    "VALUES ('默认知识库', '系统自动创建的默认知识库', :admin_id)"
                ),
                {"admin_id": admin_id},
            )
            default_kb_id = (
                await conn.execute(text("SELECT id FROM knowledge_bases ORDER BY id LIMIT 1"))
            ).scalar_one()
        else:
            default_kb_id = kb[0]
        await conn.execute(
            text("UPDATE files SET kb_id=:kb_id WHERE kb_id IS NULL"), {"kb_id": default_kb_id}
        )
    async with SessionLocal() as db:
        await reindex_missing_kb(db)
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
app.include_router(auth.router)
app.include_router(knowledge_bases.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
