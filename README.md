# 企业知识库问答系统

[English](./README.en.md) | [简体中文](./README.md)

前后端分离的企业知识库问答系统：支持账号密码登录、多知识库管理、文件解析分块、混合检索、流式多轮问答与来源引用。

## 功能概览

- **登录与用户管理**：账号密码登录，JWT 鉴权；管理员可新增用户、重置密码、删除用户。
- **个人安全**：个人改密或管理员重置密码后，该账号的旧 JWT 立即失效；新密码要求 6～128 位且非全空白。登录响应和浏览器用户缓存仅保留公开字段。
- **多知识库**：管理员创建 / 编辑 / 删除知识库，用户可查看知识库列表与统计。
- **文件管理**：支持 `md` / `txt` / `docx` / `pdf`；管理员可在指定知识库内一次最多上传 10 个文件，解析、切分和向量化在后台执行，状态为“处理中 / 就绪 / 失败”。
- **智能问答**：选择知识库后提问，支持流式输出、多轮上下文记忆、会话列表和历史记录恢复；首轮回答后自动生成简洁会话标题；知识库未命中内容时如实说明，不编造答案。
- **混合检索**：pgvector 向量检索 + LangChain Community `BM25Retriever` 关键词检索，通过 RRF 融合排序。
- **文件更新保护**：单文件默认上限 50MB；更新成功后才切换分块并递增版本，失败保留原文件和分块。
- **来源引用**：正文使用数字角标；来源弹窗按需加载单个分块并核对文件版本。旧格式仅展示保存的摘要，文件更新或删除后明确提示失效。
- **性能与上下文**：启动时为 `chunks.embedding` 创建 HNSW 余弦相似度索引；发送给大模型的最近历史消息默认限制为 20 条；超过 30 条后自动将旧消息压缩为摘要，与最近 20 条一起传给大模型。
- **系统设置**：管理员可配置分块大小、重叠窗口和 TopK。
- **安全**：按客户端来源 IP 限流，默认 15 分钟内累计失败 5 次后限制该来源 15 分钟；仅信任明确代理，计数有过期清理与容量上限。敏感操作审计日志落库。
- **自动化测试**：覆盖认证与令牌撤销、会话范围、文件更新回滚、引用加载、启动异常隔离及代理来源识别；前端使用 Node 内置测试。

当前知识库仍为登录用户共享，尚未实现成员/部门 ACL。会话必须绑定有效知识库，已绑定后不可切换；空库和未绑定旧会话的历史仍可查看。删除有关联会话的知识库或有关联数据的用户会返回 `409`。

默认管理员账号：`admin / 123456`。首次启动自动创建，请尽快修改密码。

## 技术栈

| 层次 | 选型 |
|---|---|
| 前端 | Vite + Vue 3 + Element Plus + Vue Router |
| 后端 | Python 3.13 + FastAPI + SQLAlchemy Async |
| 编排 | LangChain 1.x / LangGraph |
| 向量库 | pgvector（PostgreSQL 扩展，向量与 chunk 同库同事务） |
| 关系库 | PostgreSQL（本地 Docker） |
| Embedding | 默认 Ollama `bge-m3`；支持 OpenAI 兼容在线模型（如阿里云百炼） |
| 对话模型 | OpenAI 兼容协议（默认火山方舟，可替换其他供应商） |
| 对话记忆 | LangGraph Postgres Checkpoint |

## 项目结构

```text
backend/
  app/
    main.py               # 应用入口，负责建表、初始化数据、启动 Graph
    config.py             # 读取 backend/.env
    models.py             # SQLAlchemy 模型
    auth.py               # JWT、密码哈希、当前用户和管理员依赖
    routers/              # auth / users / knowledge-bases / files / chunks / chat / settings
    services/
      document_service.py # 文档解析、分块、向量化、状态回写
      retrieval_service.py# 向量 + BM25 混合检索，向量异常时降级 BM25
      rag_service.py      # LangGraph RAG 编排
      settings_service.py # 运行时系统设置
  requirements.txt
  .env                    # 本地配置，不提交
frontend/
  src/
    components/           # 布局和侧边栏
    views/                # 登录 / 首页 / 对话 / 知识库 / 文件 / 用户 / 设置
    router/index.js       # 路由与登录守卫
    store.js              # 全局 token、用户、会话状态
docs/                     # 需求、设计和专项方案
```

## 环境准备

1. Python 3.13
2. Node.js 20.19+（20.x）或 22.12+ / npm（按当前 Vite 的 engines 要求）
3. Docker 运行中的 PostgreSQL
4. Embedding 服务：默认使用 Ollama，并已拉取 `EMBED_MODEL`（默认 `bge-m3`）；也可改用 OpenAI 兼容在线模型
5. 大模型 API Key（OpenAI 兼容协议）

## 启动步骤

### 1. 启动 PostgreSQL

本机已创建的容器名为 `my-postgres`：

```bash
docker start my-postgres
```

### 2. 配置后端环境

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

编辑 `backend/.env`，配置 `DATABASE_URL`、`LLM_API_KEY`，并将 `JWT_SECRET` 改为随机密钥。

### 3. 启动后端

```bash
cd backend
.venv\Scripts\python run.py
```

Windows 下必须使用 `run.py` 启动，因为它会为 psycopg Async 指定 `SelectorEventLoop`。不要直接使用 `uvicorn app.main:app`。

首次启动会自动：

- 创建数据表；
- 创建默认管理员 `admin / 123456`；
- 创建「默认知识库」；
- 初始化 LangGraph Postgres Checkpoint；
- 初始化系统设置默认值。

启动时会补齐缺失向量：每个文件独立提交，失败回滚并记录日志，其他文件继续处理。补齐失败不会单独阻断应用启动，但数据库和 Checkpoint 初始化仍须成功；失败文件可在依赖恢复后重启重试。后台任务运行在应用进程内，尚不支持任务持久化或断点续传。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开：http://localhost:5173

## 配置说明

`backend/.env` 主要配置：

| 配置项 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `UPLOAD_DIR` / `EMBED_DIM` | 上传文件目录、向量维度（默认 1024，对应 bge-m3） |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块参数默认值 |
| `TOP_K` | TopK 默认值 |
| `RETRIEVAL_MIN_SCORE` | 向量相似度阈值（默认 `0.5`，越低越宽松） |
| MAX_HISTORY_MESSAGES | 发送给大模型的最近历史消息数（默认 20） |
| SUMMARY_TRIGGER_MESSAGES | 总消息数达到此值后触发摘要（默认 30） |
| SUMMARY_BATCH_SIZE | 每次摘要处理的旧消息条数（默认 10） |
| MAX_UPLOAD_MB | 单个上传文件大小上限，单位 MB（默认 50） |
| `EMBED_PROVIDER` | Embedding 供应商：`ollama` 或 `openai` |
| `OLLAMA_BASE_URL` / `EMBED_MODEL` | 本地 Embedding 服务和模型 |
| `EMBED_OPENAI_BASE_URL` / `EMBED_OPENAI_API_KEY` | OpenAI 兼容在线 Embedding 地址和密钥 |
| `EMBED_OPENAI_DIMENSIONS` / `EMBED_DIM` | 在线模型输出维度和 PostgreSQL 向量列维度，必须一致 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 大模型接口配置（OpenAI 兼容协议） |
| `JWT_SECRET` / `JWT_EXPIRE_HOURS` | JWT 签发配置 |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | 来源 IP 的失败阈值、计数窗口及限制时长，默认 5 次 / 15 分钟 |
| `TRUSTED_PROXY_IPS` | 可信代理地址列表，本地默认 `127.0.0.1,::1`；Compose 使用固定前端代理地址 |

注意：管理员在「系统设置」页保存的 `CHUNK_SIZE`、`CHUNK_OVERLAP`、`TOP_K` 优先于 `.env` 中的默认值。

切换在线 Embedding 时，请确认 `EMBED_DIM` 与模型输出维度一致。例如阿里云百炼 `text-embedding-v3` 可配置 `1024`。不同维度模型之间切换需要清空并重建已有向量数据。

## Docker 部署

在项目根目录创建 `.env`（参考 `backend/.env.example`），至少填写 `JWT_SECRET` 和 `LLM_API_KEY`，然后：

```bash
docker compose up -d --build
```

浏览器访问 `http://localhost:8080`（通过 `FRONTEND_PORT` 变量可修改端口）。数据通过 Docker Volume 持久化。

登录限流依赖可信代理边界：Compose 将前端代理固定在 `172.30.250.3`，后端只信任该地址。若代理网段与本机网络冲突，在根目录 `.env` 同时调整 `QA_PROXY_SUBNET`（默认 `172.30.250.0/24`）和其内的 `QA_PROXY_IP`，然后重建服务网络，无需删除数据卷。额外反向代理及多实例部署参见 [登录防暴力破解设计](docs/登录防暴力破解设计.md)，不要将可信代理配置为 `*`。

## 运行测试

以下命令在 Windows PowerShell 中运行，测试依赖按需安装到后端虚拟环境：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio httpx aiosqlite
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
```

```powershell
cd frontend
node --test tests/*.spec.js
npm run build
```

后端默认使用 SQLite 内存库和模拟模型，不需要真实模型服务；两项真实检索回归默认跳过。集成验证需准备 PostgreSQL、Embedding 服务及 `tests/test_retrieval_regression.py` 中配置的知识库/样例文件，按实际环境调整 ID 和预期来源；在 `backend/` 设置 `$env:RUN_RETRIEVAL_TESTS='1'` 后运行 `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval_regression.py -q`。截至 2026-11-11：后端 118 通过、2 跳过，前端 50 通过；这不包含 Docker 端到端部署或并发压测。

## 升级说明

- 本批修复无新增运行依赖和数据库结构迁移，已有上传文件布局兼容。
- 密码版本校验会拒绝不含该字段的旧 JWT，升级后可能需要重新登录；浏览器下次加载时会清理旧用户缓存中的敏感字段，无法撤回已被复制到其他位置的数据。
- 引用全文不保留跨弹窗缓存。缺少稳定定位信息的旧引用无法恢复完整历史原文；文件更新后，旧引用只能展示消息中保存的摘要。
- 来源限流为单进程内存状态，重启清空，同一公网 NAT 地址共享额度。多实例和额外反向代理需单独设计统一限流与信任边界。

## 使用流程

1. 使用 `admin / 123456` 登录。
2. 进入「知识库」，创建或选择知识库。
3. 在知识库内上传文件（单次最多 10 个），等待状态从“处理中”变为“就绪”。
4. 进入「对话」，选择知识库后提问。
5. 首条消息发送后会自动生成会话；左侧列表可继续会话或删除会话。
6. 管理员可在右上角进入「系统设置」，调整检索与分块参数。

## 文档

- [`docs/需求文档.md`](docs/需求文档.md)
- [`docs/设计文档.md`](docs/设计文档.md)
- [`docs/检索优化需求与设计.md`](docs/检索优化需求与设计.md)
- [`docs/关键词检索优化设计.md`](docs/关键词检索优化设计.md)
- [`docs/异步向量化设计.md`](docs/异步向量化设计.md)
- [`docs/docx切分优化设计.md`](docs/docx切分优化设计.md)
- [`docs/pgvector迁移设计.md`](docs/pgvector迁移设计.md)
- [`docs/登录防暴力破解设计.md`](docs/登录防暴力破解设计.md)
- [docs/审计日志与自动化测试设计.md](docs/审计日志与自动化测试设计.md)
- [docs/对话上下文摘要策略设计.md](docs/对话上下文摘要策略设计.md)
- [docs/变更记录.md](docs/变更记录.md)

后续以这些文档作为需求与实现对齐基线。
