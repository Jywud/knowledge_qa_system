# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

编码规范、命名约定和 PR 要求见 `AGENTS.md`，此处不重复。用户可见文案一律中文。

## 常用命令

后端（Windows 下必须用 `run.py` 启动，它为 psycopg Async 指定 `SelectorEventLoop`；直接 `uvicorn app.main:app` 会挂）：

```bash
cd backend
.venv\Scripts\python run.py                       # 启动后端（端口 8000）
.venv\Scripts\python -m pytest tests/ -v          # 全部测试
.venv\Scripts\python -m pytest tests/test_auth.py -v            # 单个文件
.venv\Scripts\python -m pytest tests/test_auth.py::test_name -v # 单个测试
.venv\Scripts\python -m py_compile app/xxx.py     # 触碰模块的编译检查（无 lint 配置）
```

测试不需要 PostgreSQL、Ollama 或 LLM：`tests/conftest.py` 用 `sqlite+aiosqlite` 内存库替换 `get_db`，外部服务均在测试内打桩。

前端：

```bash
cd frontend
npm run dev      # 开发服务器 http://localhost:5173
npm run build    # 构建验证（改动后必须跑）
```

## 架构要点（跨文件才能看清的部分）

### 请求链路

Vue 页面 → FastAPI 路由（`app/routers/`）→ 服务层（`app/services/`）→ SQLAlchemy（`app/models.py` 集中定义所有模型）。鉴权依赖在 `app/auth.py`（`get_current_user` / 管理员校验），审计日志在 `app/audit.py`。

### 无迁移框架：schema 靠 main.py lifespan 维护

`app/main.py` 的 `lifespan` 在每次启动时幂等地执行全部建库逻辑：`create_all` + 一串 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + HNSW 索引 + 种子数据 + 故障恢复（重启前 `processing` 状态的文件改为 `failed`）+ 缺失向量重建。**新增列时必须改两处**：`models.py` 加字段，`lifespan` 里加对应的 `ALTER TABLE` 语句，否则已有数据库不会升级。

### RAG 编排（app/services/rag_service.py）

LangGraph 图：`START → summarize → chat`，经 `build_graph(checkpointer)` 编译后挂到 `app.state.graph`，由 `routers/chat.py` 以 `thread_id = f"user-{uid}-conv-{cid}"` 调用。

- **记忆双轨**：完整历史存两处——LangGraph Postgres Checkpoint（图状态）和 `messages` 表（SSE 结束后写入）。checkpoint 是上下文来源，`messages` 表是历史恢复来源。
- **防无限增长**：`summarize` 节点把 `summarized_count` 之前、最近 `max_history_messages` 条之外的旧消息滚动压缩成 `summary`；`chat` 节点只发送 `[system, summary?, 最近N条]` 给 LLM。
- **引用闭环**：prompt 强制"未引用不标 `[来源N]`"，`chat.py` 在流结束后用正则提取回答中实际出现的来源编号过滤 sources，再按文件分组落库。
- 会话删除必须同时 `checkpointer.adelete_thread(...)`（见 `routers/chat.py`）。

### 混合检索（app/services/retrieval_service.py）

`hybrid_search` = pgvector 余弦检索（阈值 `retrieval_min_score`，建了 HNSW 索引）+ BM25 关键词检索，RRF（k=60）融合。注意：BM25 是**每次请求把 KB 全部 chunk 读入内存重建**，`_chunk_key` 用 `(file_id, chunk_index)` 去重合并——改检索逻辑时保持这个键稳定。

### 文档摄取（app/services/document_service.py）

解析（docx 用原生 zipfile+ElementTree，pdf 用 PyMuPDF）→ 表格感知分块（Markdown 表格按"表头: 单元格"拆行再聚合）→ 向量化 → 与 chunk 同事务写 `chunks` 表。**Embedding 维度不可随意改**：`embedding` 列是 `Vector(settings.embed_dim)`，换模型/维度需清空 chunks 重建，且已生成向量与新查询向量不可混用。

### 配置优先级

`SystemSetting` 数据库行（管理员在设置页保存）覆盖 `.env` 的 `chunk_size`/`chunk_overlap`/`top_k`；其余配置只读 `.env`。Embedding 提供商可切换：`EMBED_PROVIDER=ollama | openai`（OpenAI 兼容协议，如 DashScope）。

### 前端

`src/store.js` 持有全局 token/用户/会话状态，`src/router/index.js` 有登录守卫；对话流式输出在 `ChatView.vue` 里消费 SSE（`data: {...}\n\n` 事件：`start`/`token`/`sources`/`error`/`done`）。CSS 用 `style.css` 的变量，不硬编码颜色。

## 已知取舍（改动前先了解）

- BM25 每请求全量加载（见上），数据量大时会成为瓶颈；候选改进是 PostgreSQL 全文检索（zhparser/pg_jieba）。
- `hybrid_search` 中向量结果为空会直接返回空，跳过 BM25——有意的保守行为，改动需考虑 embedding 服务故障时的行为。
- 测试覆盖：登录/用户/文件/检索回归（`tests/test_retrieval_regression.py`）；RAG 或检索改动需按 `AGENTS.md` 要求在 PR 中记录人工测试问题与期望来源。
