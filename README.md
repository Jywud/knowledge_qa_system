# 企业知识库问答系统

前后端分离的企业知识库问答系统：支持账号密码登录、多知识库管理、文件解析分块、混合检索、流式多轮问答与来源引用。

## 功能概览

- **登录与用户管理**：账号密码登录，JWT 鉴权；管理员可新增用户、重置密码、删除用户。
- **多知识库**：管理员创建 / 编辑 / 删除知识库，用户可查看知识库列表与统计。
- **文件管理**：支持 `md` / `txt` / `docx` / `pdf`；管理员可在指定知识库内上传、更新、删除文件并查看分块。
- **智能问答**：选择知识库后提问，支持流式输出、多轮上下文记忆、会话列表和历史记录恢复。
- **混合检索**：Chroma 向量检索 + LangChain Community `BM25Retriever` 关键词检索，通过 RRF 融合排序。
- **系统设置**：管理员可配置分块大小、重叠窗口和 TopK。
- **安全**：登录防暴力破解（连续失败锁定）；敏感操作审计日志落库。
- **自动化测试**：覆盖登录、用户管理、文件上传核心链路。

默认管理员账号：`admin / 123456`。首次启动自动创建，请尽快修改密码。

## 技术栈

| 层次 | 选型 |
|---|---|
| 前端 | Vite + Vue 3 + Element Plus + Vue Router |
| 后端 | Python 3.13 + FastAPI + SQLAlchemy Async |
| 编排 | LangChain 1.x / LangGraph |
| 向量库 | ChromaDB（本地持久化） |
| 关系库 | PostgreSQL（本地 Docker） |
| Embedding | Ollama `bge-m3` |
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
    routers/              # auth / users / knowledge-bases / files / chat / settings
    services/
      document_service.py # 文档解析、分块、向量化、删除向量
      retrieval_service.py# 向量 + BM25 混合检索
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
2. Node.js / npm
3. Docker 运行中的 PostgreSQL
4. Ollama，并已拉取 `bge-m3`
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

编辑 `backend/.env`，至少填写 `DATABASE_URL` 和 `LLM_API_KEY`。

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
| `UPLOAD_DIR` / `CHROMA_DIR` | 上传文件和向量库目录 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块参数默认值 |
| `TOP_K` | TopK 默认值 |
| `OLLAMA_BASE_URL` / `EMBED_MODEL` | 本地 Embedding 服务和模型 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 大模型接口配置（OpenAI 兼容协议） |
| `JWT_SECRET` / `JWT_EXPIRE_HOURS` | JWT 签发配置 |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | 登录防暴力破解配置 |

注意：管理员在「系统设置」页保存的 `CHUNK_SIZE`、`CHUNK_OVERLAP`、`TOP_K` 优先于 `.env` 中的默认值。

## Docker 部署

在项目根目录创建 `.env`（参考 `backend/.env.example`），至少填写 `JWT_SECRET` 和 `LLM_API_KEY`，然后：

```bash
docker compose up -d --build
```

浏览器访问 `http://localhost:8080`（通过 `FRONTEND_PORT` 变量可修改端口）。数据通过 Docker Volume 持久化。

## 运行测试

```bash
cd backend
.venv\Scripts\python -m pytest tests/ -v
```

## 使用流程

1. 使用 `admin / 123456` 登录。
2. 进入「知识库」，创建或选择知识库。
3. 在知识库内上传文件，等待解析和向量化完成。
4. 进入「对话」，选择知识库后提问。
5. 首条消息发送后会自动生成会话；左侧列表可继续会话或删除会话。
6. 管理员可在右上角进入「系统设置」，调整检索与分块参数。

## 文档

- [`docs/需求文档.md`](docs/需求文档.md)
- [`docs/设计文档.md`](docs/设计文档.md)
- [`docs/检索优化需求与设计.md`](docs/检索优化需求与设计.md)
- [`docs/登录防暴力破解设计.md`](docs/登录防暴力破解设计.md)
- [`docs/审计日志与自动化测试设计.md`](docs/审计日志与自动化测试设计.md)

后续以这些文档作为需求与实现对齐基线。
