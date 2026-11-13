# PostgreSQL 全文检索（zhparser）替换 BM25 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关键词检索从每请求内存重建 BM25 改为 PostgreSQL 全文检索（zhparser 词级分词 + 表达式 GIN 索引），`hybrid_search` 接口与融合逻辑不变。

**Architecture:** 新增 `_fts_search`（与 `_vector_search` 同构：同权限谓词、同列集、AND 零命中 OR 兜底）；`ensure_fts` 在 lifespan 幂等启用扩展/配置/GIN 索引，失败仅降级记日志；自建 PG 镜像编译 SCWS+zhparser，compose db 与本机 my-postgres（复用 `postgres_data` 卷）都换用该镜像。降级语义四象限见设计稿。

**Tech Stack:** PostgreSQL 16 + zhparser(SCWS)、docker multi-stage、SQLAlchemy text() SQL、pytest（默认 SQLite 套件 + FTS_POSTGRES_TESTS 门控）。

**执行环境备注：** Windows + Git Bash；后端命令按 CLAUDE.md 用 `.venv\Scripts\python`（Git Bash 下亦可写 `./.venv/Scripts/python`）。设计稿：`docs/superpowers/specs/2026-11-13-pg-fts-keyword-search-design.md`。Task 3 动用户本机容器，用户已确认。提交直接在 master（仓库惯例）。

---

### Task 1: 自建 PostgreSQL 镜像（Dockerfile + 分词探针 + 固定版本）

**Files:**
- Create: `backend/docker/Dockerfile.pgvector`

- [ ] **Step 1: 写 Dockerfile**

```dockerfile
# 自建 PostgreSQL 16 镜像：pgvector 基础上编译 SCWS + zhparser，提供中文全文检索。
# 构建上下文为仓库根目录：docker build -f backend/docker/Dockerfile.pgvector -t knowledge-qa/pg16-zhparser:latest .

FROM pgvector/pgvector:pg16 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates wget bzip2 git postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*

# SCWS 1.2.3：zhparser 的底层分词库。若该地址不可达，改用可达的官方镜像源并把 URL 固定在此（记录到 PR）
RUN wget -q http://www.xunsearch.com/scws/down/scws-1.2.3.tar.bz2 \
    && tar -xjf scws-1.2.3.tar.bz2 \
    && cd scws-1.2.3 && ./configure --prefix=/usr/local && make && make install

# zhparser：首次构建后把探针记录的 commit 固化（将下方 clone 改为完整 clone + checkout <hash>）
RUN git clone --depth 1 https://github.com/amutu/zhparser.git /tmp/zhparser \
    && echo "ZHPARSER_PIN=$(git -C /tmp/zhparser rev-parse HEAD)" \
    && make -C /tmp/zhparser install

FROM pgvector/pgvector:pg16

COPY --from=builder /usr/lib/postgresql/16/lib/zhparser.so /usr/lib/postgresql/16/lib/
COPY --from=builder /usr/share/postgresql/16/extension/zhparser.control /usr/share/postgresql/16/extension/
COPY --from=builder /usr/share/postgresql/16/extension/zhparser--*.sql /usr/share/postgresql/16/extension/
COPY --from=builder /usr/local/lib/libscws.so* /usr/local/lib/
RUN ldconfig
```

注：zhparser 自带词典文件（`dict.utf8.xdb` / `rules.utf8.ini`）的安装路径以构建输出为准；若探针报词典缺失，按报错路径在 runtime 段补对应 `COPY --from=builder` 行并重建。

- [ ] **Step 2: 构建镜像**

```bash
cd "d:/myproject/ai_lerne/knowledge_qa_system"
docker build -f backend/docker/Dockerfile.pgvector -t knowledge-qa/pg16-zhparser:latest .
```

预期：构建成功；记下输出里 `ZHPARSER_PIN=<hash>` 一行。若 SCWS 下载失败，按 Step 1 注释换源重试。

- [ ] **Step 3: 分词探针（设计稿的核验门槛）**

```bash
docker run --rm -d --name zhprobe -e POSTGRES_PASSWORD=probe -e POSTGRES_DB=probe knowledge-qa/pg16-zhparser:latest
sleep 8
docker exec zhprobe psql -U postgres -d probe -c "CREATE EXTENSION zhparser;"
docker exec zhprobe psql -U postgres -d probe -c "CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);"
docker exec zhprobe psql -U postgres -d probe -c "ALTER TEXT SEARCH CONFIGURATION zh ADD MAPPING FOR n,v,a,i,e,l WITH simple;"
docker exec zhprobe psql -U postgres -d probe -c "SET zhparser.punctuation_ignore=on; SET zhparser.multi_short=on; SELECT to_tsvector('zh','企业知识库的检索权限配置指南'); SELECT to_tsvector('zh','XQ-300型号的维护手册'); SELECT to_tsvector('zh','混合检索使用RRF融合排序算法');"
docker rm -f zhprobe
```

验收标准（记录输出到 PR）：三条 `to_tsvector` 输出为**词级** lexeme——"检索""权限"等成词而非单字；"XQ-300" 的字母数字段保留为 token；报错（如词典文件缺失）则按 Step 1 注释补 COPY 行重建后重跑探针。

- [ ] **Step 4: 固定 zhparser 版本**

把 Step 3 记录的 hash 写死进 Dockerfile（用 Edit 工具把 `--depth 1` 那段 RUN 替换为）：

```dockerfile
RUN git clone https://github.com/amutu/zhparser.git /tmp/zhparser \
    && git -C /tmp/zhparser checkout <Step2记录的hash> \
    && make -C /tmp/zhparser install
```

然后重新构建一次确认仍成功（`docker build` 同 Step 2）。

- [ ] **Step 5: Commit**

```bash
git add backend/docker/Dockerfile.pgvector
git commit -m "feat: add pgvector+zhparser custom postgres image

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: fts_service.ensure_fts + lifespan 接入 + compose 换镜像

**Files:**
- Create: `backend/app/services/fts_service.py`
- Modify: `backend/app/main.py:41-47`（`_initialize_database` 的 `engine.begin` 块）
- Modify: `docker-compose.yml:2-3`（db 服务）

- [ ] **Step 1: 新建 fts_service.py**

```python
"""zhparser 中文全文检索的幂等初始化：扩展、检索配置、数据库级分词参数与表达式 GIN 索引。

调整分词参数（下方 ALTER DATABASE 两项）或检索配置映射后，
必须重建索引：REINDEX INDEX idx_chunks_content_fts，否则索引与查询的分词口径不一致。
"""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

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
    await conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS {FTS_INDEX_NAME} "
        "ON chunks USING GIN (to_tsvector('zh'::regconfig, content))"))
```

（GUC 取值 `punctuation_ignore=on`、`multi_short=on` 来自设计稿意图，Task 1 探针若显示不合适，此处与探针结论同步调整。）

- [ ] **Step 2: lifespan 接入（create_all 之后、HNSW 之前）**

`backend/app/main.py` 的 `_initialize_database` 中，把

```python
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        ))
```

改为

```python
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        try:
            from app.services.fts_service import ensure_fts
            await ensure_fts(conn)
        except Exception:
            logger.exception("zhparser 全文检索初始化失败，关键词检索将降级为纯向量结果；"
                             "生产部署请使用自建 PostgreSQL 镜像（backend/docker/Dockerfile.pgvector）")
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        ))
```

- [ ] **Step 3: compose db 服务换镜像**

`docker-compose.yml` 的 db 服务开头改为（其余字段不动）：

```yaml
  db:
    build:
      context: .
      dockerfile: backend/docker/Dockerfile.pgvector
    image: knowledge-qa/pg16-zhparser:latest
    restart: unless-stopped
```

- [ ] **Step 4: 编译与配置校验**

```bash
cd backend && ./.venv/Scripts/python -m py_compile app/services/fts_service.py app/main.py && cd ..
docker compose config --quiet
```

预期：两条命令无输出、退出码 0。（真实 DDL 验证在 Task 3 启动后端时进行；SQLite 套件不跑 lifespan，无需适配。）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/fts_service.py backend/app/main.py docker-compose.yml
git commit -m "feat: idempotent zhparser FTS setup in lifespan and custom compose db image

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 重建本机 my-postgres 容器（复用 postgres_data 卷）

**Files:** 无代码文件；操作用户本机 Docker（已获用户确认）。

- [ ] **Step 1: 记录现有容器配置**

```bash
docker inspect my-postgres --format '{{json .Config.Env}}'
docker inspect my-postgres --format '{{json .HostConfig.PortBindings}}'
docker inspect my-postgres --format '{{json .HostConfig.RestartPolicy}}'
```

已知事实：数据卷为 `postgres_data`（命名卷）；`backend/.env` 的 `DATABASE_URL` 为 `postgresql://postgres:postgres@localhost:5432/knowledge_qa`（POSTGRES_* 环境变量对已有卷无效，仅作记录用途）。端口映射与重启策略以 inspect 输出为准。

- [ ] **Step 2: 重建容器**

```bash
docker rm -f my-postgres
docker run -d --name my-postgres --restart unless-stopped \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  knowledge-qa/pg16-zhparser:latest
```

（`-p`、`--restart` 用 Step 1 实际记录值；POSTGRES_* 环境变量因卷已初始化可不带。）PG 大版本同为 16，`postgres_data` 直接兼容。

- [ ] **Step 3: 验证数据完好**

```bash
docker exec my-postgres psql -U postgres -d knowledge_qa -c "SELECT count(*) AS files FROM files; SELECT count(*) AS chunks FROM chunks;"
```

预期：数量与重建前一致（重建前可先跑一次本命令留底）。

- [ ] **Step 4: 启动后端验证 lifespan DDL**

```bash
cd backend && ./.venv/Scripts/python run.py
```

启动日志无 `zhparser 全文检索初始化失败` 字样；随后（另开终端）验证：

```bash
docker exec my-postgres psql -U postgres -d knowledge_qa -c "SELECT cfgname FROM pg_ts_config WHERE cfgname='zh';"
docker exec my-postgres psql -U postgres -d knowledge_qa -c "SELECT indexname FROM pg_indexes WHERE indexname='idx_chunks_content_fts';"
docker exec my-postgres psql -U postgres -d knowledge_qa -c "SHOW zhparser.multi_short;"
```

预期：`zh` 配置存在、索引存在、`multi_short` 为 `on`。验证后 Ctrl+C 停掉后端。

- [ ] **Step 5: 无提交（纯运维步骤）**

---

### Task 4: 门控 PostgreSQL FTS 测试（TDD 红灯）

**Files:**
- Create: `backend/tests/test_fts_postgres.py`
- Modify: `backend/pytest.ini`（markers 段）

- [ ] **Step 1: pytest.ini 加 marker**

```ini
[pytest]
asyncio_mode = auto
markers =
    retrieval: 需要本地 PostgreSQL + Ollama 的检索回归用例（RUN_RETRIEVAL_TESTS=1 启用）
    fts: 需要本地 PostgreSQL + zhparser 的全文检索用例（FTS_POSTGRES_TESTS=1 启用）
```

- [ ] **Step 2: 写门控测试文件（此时 `_fts_search` 尚不存在，预期失败）**

```python
"""显式启用的 PostgreSQL zhparser 全文检索验证；随机 schema 隔离，不污染开发数据。"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text
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
    """遮蔽 conftest 的 SQLite fixture（同 test_roles_postgres.py 的既有模式）。"""
    schema = "fts_test_" + uuid4().hex
    isolated = create_async_engine(
        engine.url, connect_args={"server_settings": {"search_path": f"{schema},public"}})
    factory = async_sessionmaker(isolated, expire_on_commit=False)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with isolated.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_fts(conn)
        async with factory() as db:
            db.add(User(id=1, username="admin", password_hash=hash_password("x")))
            db.add(User(id=2, username="alice", password_hash=hash_password("x")))
            db.add(Role(id=2, name="测试角色"))
            db.add(UserRole(user_id=2, role_id=2))
            db.add(RoleKnowledgeBase(role_id=2, kb_id=1))
            db.add(KnowledgeBase(id=1, name="已授权库", created_by=1))
            db.add(KnowledgeBase(id=2, name="未授权库", created_by=1))
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
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


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
```

（fixture 内中文语料如与探针实测分词不符导致断言失败，调整语料字符串而非断言逻辑。）

- [ ] **Step 3: 运行确认红灯**

```bash
cd backend && FTS_POSTGRES_TESTS=1 ./.venv/Scripts/python -m pytest tests/test_fts_postgres.py -v
```

预期：`test_hybrid_degrades_to_fts_when_embedding_fails` 等 5 个用例 FAIL，错误为 `AttributeError: ... has no attribute '_fts_search'`（fixture 本身通过）。

- [ ] **Step 4: Commit（红灯也提交，TDD 惯例）**

```bash
git add backend/tests/test_fts_postgres.py backend/pytest.ini
git commit -m "test: add gated postgres fts tests (red)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: _fts_search 实现 + hybrid_search 重构 + SQLite 测试适配（转绿）

**Files:**
- Modify: `backend/app/services/retrieval_service.py`（全文重构，见下）
- Modify: `backend/tests/test_retrieval_permissions.py`（替换 1 个测试、新增 1 个）
- Modify: `backend/tests/test_sources.py:22-36`（替换 1 个测试）
- Modify: `backend/tests/test_multi_kb_chat.py:107-115`（替换 1 个测试）

- [ ] **Step 1: 重写 retrieval_service.py**

删除：`from langchain_community.retrievers import BM25Retriever`、`CHINESE_STOP_CHARS`、`tokenize_for_search`、`_bm25_search`、`hybrid_search` 里加载全量 rows 的 SQLAlchemy 查询块。保留：`_row_document`、`_chunk_key`、`_merge_candidates`、`_require_context`、`_vector_search` 原样不动。

文件头部 import 改为（`re`/`select`/`Chunk`/`FileRecord`/`KnowledgeBase`/`readable_kb_predicate` 均只被被删代码引用，一并移除；`settings` 仅 `_vector_search` 用，保留）：

```python
import logging

from langchain_core.documents import Document
from sqlalchemy import text
from fastapi import HTTPException

from app.services.document_service import get_embeddings
from app.config import settings

logger = logging.getLogger(__name__)
```

新增 FTS 检索函数（放在 `_vector_search` 之后）：

```python
FTS_PERMISSION = """
    (EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
             WHERE ur.user_id = :user_id AND r.system_key = 'system_admin')
     OR EXISTS (SELECT 1 FROM user_roles ur JOIN role_knowledge_bases rk ON rk.role_id = ur.role_id
                WHERE ur.user_id = :user_id AND rk.kb_id = f.kb_id))
"""


async def _fts_search(query: str, kb_id: int | None, limit: int, *, user_id: int | None = None,
                      kb_ids: list[int] | None = None) -> list[Document]:
    """zhparser 词级全文检索；AND 零命中时以分词 OR 组合兜底并按 ts_rank 排序。"""
    from app.database import SessionLocal

    _require_context(kb_id, user_id, kb_ids)
    params: dict = {"user_id": user_id, "k": limit, "q": query}
    statement = f"""
        SELECT c.id AS chunk_id, c.file_id, c.chunk_index, c.page_no, c.content,
               f.kb_id, f.filename, f.file_type, f.created_at, f.version AS file_version,
               kb.name AS kb_name
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        JOIN knowledge_bases kb ON kb.id = f.kb_id
        WHERE {FTS_PERMISSION}
          AND to_tsvector('zh'::regconfig, c.content) @@ plainto_tsquery('zh'::regconfig, :q)
    """
    if kb_id:
        statement += " AND f.kb_id = :kb_id"
        params["kb_id"] = kb_id
    if kb_ids is not None:
        statement += " AND f.kb_id = ANY(CAST(:kb_ids AS INTEGER[]))"
        params["kb_ids"] = kb_ids
    statement += (" ORDER BY ts_rank(to_tsvector('zh'::regconfig, c.content), "
                  "plainto_tsquery('zh'::regconfig, :q)) DESC LIMIT :k")

    async with SessionLocal() as db:
        rows = (await db.execute(text(statement), params)).all()
        if rows:
            return [_row_document(row) for row in rows]

        # AND 零命中：用 zhparser 自身分词结果构造 OR 查询；词面加引号防 tsquery 操作符注入
        lexemes = (await db.execute(text(
            "SELECT DISTINCT lexeme FROM unnest(to_tsvector('zh'::regconfig, :q)) "
            "ORDER BY lexeme"), {"q": query})).scalars().all()
        if not lexemes:
            return []
        or_params = dict(params)
        or_params.pop("q", None)
        or_params["or_query"] = " | ".join("'" + lex.replace("'", "''") + "'" for lex in lexemes)
        or_statement = statement.replace(
            "plainto_tsquery('zh'::regconfig, :q)", "to_tsquery('zh'::regconfig, :or_query)")
        rows = (await db.execute(text(or_statement), or_params)).all()
    return [_row_document(row) for row in rows]
```

`hybrid_search` 整体替换为：

```python
async def hybrid_search(query: str, kb_id: int | None, top_k: int, *, user_id: int | None = None,
                        kb_ids: list[int] | None = None) -> list[Document]:
    _require_context(kb_id, user_id, kb_ids)
    if kb_id is not None and kb_ids is not None and kb_id not in kb_ids:
        return []
    candidate_k = max(top_k * 2, 10)
    try:
        query_vector = await get_embeddings().aembed_query(query)
        vector_docs = await _vector_search(query_vector, kb_id, candidate_k, user_id=user_id, kb_ids=kb_ids)
    except Exception:
        logger.exception("向量检索失败，降级为纯关键词结果")
        vector_docs = None
    if vector_docs is not None and not vector_docs:
        return []  # 保守行为保持：向量零命中直接返回空，不引入关键词噪声
    try:
        keyword_docs = await _fts_search(query, kb_id, candidate_k, user_id=user_id, kb_ids=kb_ids)
    except Exception:
        logger.exception("关键词检索失败，降级为纯向量结果")
        keyword_docs = []
    if vector_docs is None:
        return keyword_docs[:top_k]
    return _merge_candidates(vector_docs, keyword_docs, top_k)
```

- [ ] **Step 2: 适配 test_retrieval_permissions.py**

文件顶部 import 增加 `from langchain_core.documents import Document`。删除 `test_keyword_fallback_never_reads_ungranted_library`（其 seeding 语句随之删除；`Chunk`/`FileRecord`/`KnowledgeBase` import 若因此不再使用则一并移除），替换为下面两个测试（无权限过滤已移至门控测试的真实 SQL 验证）：

```python
async def test_conflicting_scope_short_circuits_before_channels(test_db, monkeypatch):
    embed = AsyncMock(side_effect=RuntimeError("不应触发向量通道"))
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(aembed_query=embed))
    fts = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval_service, "_fts_search", fts)
    assert await retrieval_service.hybrid_search("needle", 1, 5, user_id=2, kb_ids=[2]) == []
    embed.assert_not_awaited()
    fts.assert_not_awaited()


async def test_vector_failure_falls_back_to_keyword_channel(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    doc = Document(page_content="needle source document",
                   metadata={"chunk_id": "7", "file_id": "1", "chunk_index": "0", "file_version": 1})
    async def fake_fts(query, kb_id, limit, *, user_id=None, kb_ids=None):
        assert kb_id == 1 and user_id == 2
        return [doc]
    monkeypatch.setattr(retrieval_service, "_fts_search", fake_fts)
    docs = await retrieval_service.hybrid_search("needle", 1, 5, user_id=2)
    assert [d.metadata["chunk_id"] for d in docs] == ["7"]
    assert docs[0].metadata["file_version"] == 1
```

- [ ] **Step 3: 适配 test_sources.py 与 test_multi_kb_chat.py**

`test_sources.py`：`test_keyword_retrieval_keeps_reference_identity` 整体替换为（真实行映射已由门控测试覆盖，此处验证元数据透传）：

```python
async def test_keyword_fallback_keeps_reference_identity(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    doc = Document(page_content="needle reference document",
                   metadata={"chunk_id": "7", "file_id": "1", "chunk_index": "0", "file_version": 3})
    async def fake_fts(query, kb_id, limit, *, user_id=None, kb_ids=None):
        return [doc]
    monkeypatch.setattr(retrieval_service, "_fts_search", fake_fts)
    docs = await retrieval_service.hybrid_search("needle", 1, 5, user_id=1)
    assert str(docs[0].metadata["chunk_id"]) == "7"
    assert docs[0].metadata["file_version"] == 3
```

（该文件中 seeding Chunk/FileRecord 的语句随之删除；`Chunk`/`FileRecord` import 若因此不再使用则一并移除。）

`test_multi_kb_chat.py`：`test_all_scope_keyword_fallback_intersects_permissions_and_snapshot` 整体替换为（范围交集由门控测试的真实 SQL 验证，此处验证快照参数透传与范围冲突短路）：

```python
async def test_all_scope_keyword_fallback_passes_scope_and_snapshot(client, test_db, monkeypatch):
    await seed(client, test_db)
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    fts = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval_service, "_fts_search", fts)
    assert await retrieval_service.hybrid_search("needle", None, 5, user_id=2, kb_ids=[1, 2, 3]) == []
    assert fts.await_args.args == ("needle", None, 5)
    assert fts.await_args.kwargs["kb_ids"] == [1, 2, 3]
    assert fts.await_args.kwargs["user_id"] == 2
```

- [ ] **Step 4: 运行门控测试确认转绿**

```bash
cd backend && FTS_POSTGRES_TESTS=1 ./.venv/Scripts/python -m pytest tests/test_fts_postgres.py -v
```

预期：5 passed。

- [ ] **Step 5: 运行默认 SQLite 全量套件**

```bash
cd backend && ./.venv/Scripts/python -m pytest tests/ -v
```

预期：全部通过（原 167+ 基线，替换 3 个测试、新增 1 个；跳过项与之前相同）。若有残留引用 `tokenize_for_search`/`_bm25_search` 的测试在此暴露，按同样"打桩"思路处理。

- [ ] **Step 6: EXPLAIN 确认走 GIN 索引（验收项 1）**

```bash
docker exec my-postgres psql -U postgres -d knowledge_qa -c "EXPLAIN SELECT id FROM chunks WHERE to_tsvector('zh'::regconfig, content) @@ plainto_tsquery('zh'::regconfig, '知识库');"
```

预期：计划含 `Bitmap Index Scan on idx_chunks_content_fts`（chunks 为空时可能显示 Seq Scan——此时先确认索引存在 `SELECT indexname FROM pg_indexes WHERE indexname='idx_chunks_content_fts';` 并记录到 PR；上传文档后再复查一次）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/retrieval_service.py backend/tests/test_retrieval_permissions.py backend/tests/test_sources.py backend/tests/test_multi_kb_chat.py
git commit -m "feat: replace in-memory BM25 with postgres zhparser full-text search

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 依赖清理 + 全量回归

**Files:**
- Modify: `backend/requirements.txt`（删 `rank_bm25>=0.2.2` 一行）

- [ ] **Step 1: 确认 BM25 无残留引用**

```bash
grep -rn "rank_bm25\|BM25Retriever\|tokenize_for_search\|CHINESE_STOP_CHARS" backend/app backend/tests
```

预期：无输出。有输出则回到 Task 5 清理。注意 `langchain_community` 本身**保留**——`document_service.py` 仍在用 `PyMuPDFLoader`/`TextLoader`。

- [ ] **Step 2: 删除 rank_bm25 依赖行**

`backend/requirements.txt` 删除 `rank_bm25>=0.2.2` 这一行（`langchain-community` 保留）。

- [ ] **Step 3: 全量回归**

```bash
cd backend && ./.venv/Scripts/python -m pytest tests/ -q
cd backend && FTS_POSTGRES_TESTS=1 ./.venv/Scripts/python -m pytest tests/test_fts_postgres.py -q
```

预期：默认套件全绿（跳过项与基线一致），门控 5 passed。前端无改动，不跑 `npm run build`。

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: drop rank_bm25 dependency after fts migration

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Compose E2E + 人工检索验证 + 文档同步

**Files:**
- Modify: `README.md`（混合检索描述、Docker 部署章节、测试章节）
- Modify: `README.en.md`（对应英文两处）
- Modify: `CLAUDE.md`（混合检索架构段、已知取舍）
- Modify: `docs/关键词检索优化设计.md`（标注已实施）
- Modify: `docs/变更记录.md`（新增条目）

- [ ] **Step 1: Compose 全链路验证**

```bash
docker compose up -d --build
docker compose ps
docker compose exec db psql -U postgres -d knowledge_qa -c "SELECT extname FROM pg_extension WHERE extname='zhparser';"
```

预期：三个服务 Up；db 里 zhparser 扩展存在（compose db 是新卷，空库属正常）。浏览器 `http://localhost:8080` 登录 `admin/123456` 可用。

- [ ] **Step 2: 人工检索验证（按 AGENTS.md 记录进 PR）**

用已有知识库（compose 验证或 my-postgres 环境均可）执行并记录"问题 → 期望来源"：

1. 上传一个含中文正文、自定义术语和型号（如 XQ-300）的 md 文件，等状态"就绪"。
2. 提问正文明示内容 → 回答引用该文档，`[来源N]` 指向正确文件与版本。
3. 提问只出现在文档里的型号/术语 → 能命中（词级分词）。
4. 提问知识库没有的内容 → 如实说明未命中，不编造。
5. 删除该文件后重问 → 不再命中。
6. FTS 异常降级验证：`docker exec my-postgres psql -U postgres -d knowledge_qa -c "DROP EXTENSION zhparser CASCADE;"` 后提问 → 仍有向量结果、日志出现"关键词检索失败，降级为纯向量结果"；然后重启后端（lifespan 幂等重建扩展、配置与索引）再问一次确认恢复。

- [ ] **Step 3: 文档同步（逐处替换，不用改写无关段落）**

`README.md`：
- "功能概览"里 `**混合检索**` 条目替换为：`**混合检索**：pgvector 向量检索 + PostgreSQL 全文检索（zhparser 中文分词，GIN 索引），通过 RRF 融合排序；向量或关键词通道异常时自动降级为单通道结果。`
- "Docker 部署"章节末尾追加一段：`数据库使用自建镜像（backend/docker/Dockerfile.pgvector，基于 pgvector/pgvector:pg16 编译 SCWS + zhparser）。调整 zhparser 分词参数或自定义词典后需在库内执行 REINDEX INDEX idx_chunks_content_fts。`
- "运行测试"的 PostgreSQL 门控说明处补充：`全文检索验证需设置 FTS_POSTGRES_TESTS=1（需要带 zhparser 的 PostgreSQL）。`

`README.en.md`：同步以上三处的英文对应内容。

`CLAUDE.md`：
- "混合检索（app/services/retrieval_service.py）"段落替换为：`hybrid_search` = pgvector 余弦检索（阈值 `retrieval_min_score`，HNSW 索引）+ PostgreSQL 全文检索（zhparser 词级分词，表达式 GIN 索引 `idx_chunks_content_fts`，AND 零命中 OR 兜底），RRF（k=60）融合。关键词检索走 `_fts_search`，权限谓词与 `_vector_search` 同构——改检索逻辑时保持返回列集与 `_row_document` 兼容。
- "已知取舍"第一条（BM25 每请求全量加载）替换为：`关键词检索依赖 zhparser 扩展（自建镜像）；扩展不可用时自动降级为纯向量检索并记日志。调整分词 GUC 或词典后需 REINDEX idx_chunks_content_fts。`

`docs/关键词检索优化设计.md`：顶部"## 背景"前加一行：`> 状态：方案 B 已于 2026-11-13 实施（PostgreSQL 全文检索 + zhparser），实施记录见 docs/superpowers/specs/2026-11-13-pg-fts-keyword-search-design.md；本文其余内容保留作决策过程记录。`

`docs/变更记录.md`：按现有格式新增 `## 2026-11-13：关键词检索切换 PostgreSQL 全文检索` 条目，列明：自建镜像、表达式 GIN 索引（无新列）、`_fts_search` 与降级语义、测试适配（3 曦换 1 新增 + 门控 5 项）、依赖删除 rank_bm25、人工测试问题与期望来源（Step 2 记录）、各项验证结果。

- [ ] **Step 4: 收尾 Commit**

```bash
git add README.md README.en.md CLAUDE.md docs/关键词检索优化设计.md docs/变更记录.md
git commit -m "docs: align docs with zhparser full-text search migration

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 验收对照（设计稿"验收"章节）

1. 无全量 chunk 读取路径 / EXPLAIN 走 GIN → Task 5 Step 6
2. 默认套件全绿 + 门控 5 passed → Task 6 Step 3
3. compose 全链路 + 自建镜像 → Task 7 Step 1
4. 文档同步四处 → Task 7 Step 3
