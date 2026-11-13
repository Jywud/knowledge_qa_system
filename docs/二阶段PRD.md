# 企业智能知识库系统 · 二阶段 PRD

版本：v1.0（2026-11-04）  
状态：待评审，评审通过后进入开发  
上游文档：[二阶段需求分析](./二阶段需求分析.md)  
下游文档：[二阶段迭代计划](./二阶段迭代计划.md)

## 1. 背景与目标

当前系统已经具备多知识库、文件解析、混合检索、流式问答、会话记忆和基础后台管理能力。二阶段目标不是增加更多“演示型 AI 功能”，而是让系统达到企业内部试运行标准：

1. 不该看的内容看不到。
2. 上传失败能发现、能重试，更新失败不毁旧数据。
3. 回答引用的原文在文件更新后仍然可追溯。
4. 用户遇到错误时知道发生了什么、下一步做什么。
5. 管理员知道系统缺哪些知识、哪些问题答不上来。

## 2. 范围

### 2.1 本期范围

- P0：权限、入库可靠性、引用稳定、对话基本体验、安全与审计。
- P1：Rerank、查询改写、知识缺口雷达、检索调试台、运营看板。
- P2：连接器、开放 API/MCP、Agentic RAG 试点（按剩余工期决定）。

### 2.2 不在本期范围

- 普通用户自建知识库。
- 多租户计费。
- 完整工作流编排器。
- 全量 GraphRAG、全量 OCR。
- 移动端原生 App。

## 3. 角色与权限矩阵

| 能力 | 系统管理员 | 知识库 owner | 知识库 editor | viewer | 普通用户 |
|---|---|---|---|---|---|
| 创建/删除知识库 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 管理知识库成员 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 上传/更新/删除文件 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 查看文件与分块 | ✅ | ✅ | ✅ | ✅ | 仅授权库 |
| 问答 | ✅ | ✅ | ✅ | ✅ | 仅授权库 |
| 查看审计日志 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 管理用户 | ✅ | ❌ | ❌ | ❌ | ❌ |

权限规则：

- `admin` 拥有全量权限。
- 知识库 `visibility=public` 时，所有登录用户可读。
- `visibility=department` 时，仅 `kb_departments` 中部门用户可读。
- `visibility=private` 时，仅 `kb_members` 中用户可读。
- 无权限访问资源返回 403；资源不存在返回 404。
- **检索必须在 SQL 层过滤 `allowed_kb_ids`，不得先检索全部再在 Prompt 中约束。**

## 4. 需求清单

| Epic | 名称 | 优先级 | 主要交付 |
|---|---|---|---|
| E1 | 知识库权限 | P0 | 成员/部门/可见性、检索过滤、权限管理页 |
| E2 | 入库可靠性 | P0 | 任务表、进度、重试、取消、版本化更新 |
| E3 | 引用与版本 | P0 | 稳定引用、原文定位、旧版本提示 |
| E4 | 对话体验 | P0 | 停止、重试、重新生成、反馈、错误态、会话管理 |
| E5 | 安全与审计 | P0 | 密码策略、限流、审计查询、健康检查 |
| E6 | 质量评估 | P0 | 评估集、离线指标、发布门禁 |
| E7 | 检索增强 | P1 | 查询改写、Rerank、元数据过滤、父块扩展、PG 全文检索 |
| E8 | 知识运营 | P1 | 知识缺口雷达、检索调试台、使用看板、健康度 |
| E9 | 开放与生态 | P2 | 连接器、OpenAI 兼容 API、MCP、Agentic RAG 试点 |

## 5. 详细需求

### E1 知识库权限

#### 用户故事

- 作为管理员，我可以设置知识库为公开、部门可见或私有，避免敏感制度被全公司看到。
- 作为知识库 owner，我可以添加/移除成员并设置 viewer/editor。
- 作为普通用户，我只在知识库列表中看到我有权访问的库。
- 作为安全负责人，我可以确认检索结果不会包含无权知识库的内容。

#### 规则

1. `GET /api/knowledge-bases` 只返回当前用户可见的知识库。
2. `GET /api/files?kb_id=`、`GET /api/chunks/{id}` 校验知识库访问权限。
3. 创建会话时必须绑定用户有权限的知识库；后续不能切换。
4. 会话绑定的知识库被删除或权限被回收时，历史仍可查看，但不能继续问答。
5. 管理员可以查看全部知识库并代管成员。
6. 知识库成员变更写入审计日志。

#### 验收标准

- 用户 A 无权访问 KB-B，列表不出现 KB-B；直接请求文件/分块/问答均返回 403。
- 用户 A 提问时，检索 SQL 的 `WHERE` 条件包含 `kb_id IN (allowed_kb_ids)`。
- 用户 A 无法通过修改请求体 `kb_id` 越权。
- 管理员移除用户 A 的 viewer 权限后，A 刷新页面立即看不到该库，已打开的会话不能继续发送。

### E2 入库可靠性

#### 用户故事

- 作为管理员，我上传 20 个文件后能看到每个文件处于解析、分块、向量化还是失败。
- 作为管理员，我可以对失败文件点击重试，不需要重新上传。
- 作为管理员，我更新文件失败时，旧版本仍然可用。
- 作为管理员，我可以看到失败原因，例如“PDF 加密”“Embedding 服务不可用”“文件为空”。

#### 规则

1. 上传接口快速返回 `file_id` 和 `job_id`，解析/向量化异步执行。
2. 任务状态：`queued → parsing → chunking → embedding → ready`，异常为 `failed`，用户取消为 `canceled`。
3. 每个任务记录 `progress`（0-100）、`attempts`、`error_message`、时间戳。
4. 自动重试最多 3 次，指数退避；Embedding 服务不可用时不无限重试。
5. 同一知识库内按 SHA-256 检测重复文件，提示“已存在相同内容”，允许管理员强制上传。
6. 更新文件采用新版本处理，成功后原子切换 `active_version`；失败保留旧版本。
7. 服务重启后，`queued/processing` 任务自动恢复或标记失败并提供重试。
8. 删除文件时，如果有历史消息引用，保留引用快照并标记“文件已删除”。

#### 验收标准

- 上传 10MB PDF，接口 2 秒内返回，列表可见进度变化。
- 停掉 Ollama 后上传，任务进入 `failed`，错误信息可读；恢复 Ollama 后可重试成功。
- 更新文件时上传一个损坏 PDF，旧版本仍可问答，文件状态显示“更新失败，当前使用 vN”。
- 服务重启后，处理中任务不会永久卡在 `processing`。
- 同一文件重复上传，提示重复并给出已有文件链接。

### E3 引用与版本

#### 用户故事

- 作为用户，我点击来源能看到命中的原文片段、页码和章节。
- 作为用户，如果引用来自旧版本，我能看到明确提示，而不是被新内容误导。
- 作为用户，如果文件已删除，我仍能看到当时的引用摘录。

#### 规则

1. `messages.sources` 存 `chunk_id`、`file_id`、`file_version`、`page`、`heading_path`、`score`、`excerpt`、`status`。
2. 来源按 `file_id` 聚合，不按文件名聚合，避免同名文件混淆。
3. 新增 `GET /api/chunks/{chunk_id}`，只返回单个分块及文件/版本元数据。
4. 历史引用不重新检索、不重新生成；只展示当时保存的摘录和版本状态。
5. 文件更新后，旧 `chunk_id` 仍可查询到旧版本内容（在保留期内）；超过保留期显示“旧版本已清理”。
6. 前端来源弹窗支持加载态、404/403/410 错误态，不出现未捕获异常。

#### 验收标准

- 引用弹窗不再请求整个文件的全部分块。
- 同一知识库存在两个同名文件时，来源分组不合并。
- 文件更新后，旧回答的来源标记“来自 v2”，新回答引用 v3，二者不串。
- 删除文件后，旧回答仍能打开摘录，并提示“文件已删除”。

### E4 对话体验

#### 用户故事

- 作为用户，我可以在回答生成过程中点击“停止”，不再等待。
- 作为用户，我可以对回答重新生成，或修改问题后重发。
- 作为用户，我可以点赞/点踩并选择原因。
- 作为用户，我刷新页面后会话、消息、引用都还在。
- 作为用户，遇到 401/429/500 时能看到明确提示和重试按钮。

#### 规则

1. **关闭页面/断网**：后台继续生成并落库，用户回到历史会话可看到完整回答。
2. **点击停止**：前端发送 `POST /api/conversations/{id}/stop`，后端取消当前生成，保存已生成部分并标记 `stopped`。
3. SSE `start` 事件返回 `generation_id`，用于停止和幂等。
4. 重新生成：保留原回答，新增一条 assistant 消息；默认不覆盖历史。
5. 反馈：`feedback` 表记录 `message_id/user_id/rating[up|down]/reason/comment`，同一用户对同一消息可修改一次。
6. 会话支持重命名、置顶、按标题搜索、导出 Markdown。
7. 会话/消息分页，默认 20 条，向上滚动加载更多。
8. 前端所有 API 错误统一处理：401 清凭证跳登录，403 提示无权限，429 提示稍后重试，5xx 显示“服务异常”并保留输入。

#### 验收标准

- 点击停止后 2 秒内停止追加 token，历史中保存已生成内容并标记“已停止”。
- 关闭浏览器后重新打开，生成中的回答最终出现在历史列表。
- 401 时不再出现空白 assistant 气泡。
- 点踩必须选择原因，反馈可在后台按知识库/时间筛选。
- 100 条会话的列表首屏加载不超过 1 秒（本地环境）。

### E5 安全与审计

#### 用户故事

- 作为管理员，我可以查询谁在什么时候上传/删除/修改了哪个文件。
- 作为管理员，我可以看到登录失败、权限变更、用户创建/删除。
- 作为安全负责人，我可以配置密码策略、登录限流和问答限流。

#### 规则

1. 密码：至少 8 位，包含字母和数字；管理员重置密码同样校验；首次登录建议强制改密。
2. 用户名：3-32 位，允许字母、数字、下划线、短横线；不允许空白。
3. 审计事件：登录成功/失败、退出、改密、用户增删/重置、知识库增删改、成员变更、文件上传/更新/删除/重试、问答限流触发。
4. 审计字段：操作人、动作、目标、结果、IP、User-Agent、详情、时间。
5. 问答限流：每用户同时 1 个生成任务；每分钟最多 N 次（默认 10，可配置）。
6. 登录限流落库或 Redis，服务重启不清零；多实例共享。
7. 生产环境 `CORS_ALLOW_ORIGINS` 必须配置白名单；`JWT_SECRET` 为默认值时启动失败。
8. 健康检查：`/api/health/live` 只检查进程；`/api/health/ready` 检查 DB、pgvector、LLM、Embedding。

#### 验收标准

- 管理员重置密码为 `1` 返回 400。
- 审计页面可按操作人、动作、时间范围筛选并导出 CSV。
- 连续失败登录达到阈值后，重启服务仍处于锁定状态。
- 单用户并发发起第二个问答返回 429 或排队提示。
- DB/LLM/Embedding 任一不可用时，`/health/ready` 返回 503 并指出失败项。

### E6 质量评估

#### 用户故事

- 作为研发，我可以在改动检索/提示词后跑一组固定问题，确认没有退化。
- 作为管理员，我可以看到当前知识库的命中率和无答案率。

#### 规则

1. 每个知识库维护 30-50 条评估问题，标注期望文件/章节/是否应回答“不知道”。
2. 离线指标：Hit@5、MRR、上下文精度、引用准确率、无答案准确率、平均耗时。
3. 评估脚本：`backend/scripts/eval_retrieval.py`，支持 `--kb-id`、`--dataset`、`--top-k`。
4. 发布门禁：P0 检索链路改动必须附评估结果；Hit@5 下降超过 5% 不允许合并。
5. 评估数据不包含真实敏感内容，使用脱敏样本。

#### 验收标准

- 一条命令可跑完评估并输出 Markdown/JSON 报告。
- 报告包含每个失败问题的期望来源、实际来源、分数。
- CI 可选运行；本地必须有运行说明。

### E7 检索增强（P1）

#### 规则

1. **查询改写**：多轮追问时生成独立问题；失败或超时 1.5 秒降级为原问题。
2. **Rerank**：召回 Top 20，重排取 Top 5；Rerank 服务失败时降级为 RRF 结果。
3. **元数据过滤**：支持文件类型、上传时间、知识库、标签过滤。
4. **父块扩展**：子块命中后取所属章节/父块，控制上下文长度。
5. **PostgreSQL 全文检索**：用 `tsvector + GIN` 替换全量内存 BM25；中文分词优先 `pg_jieba`/`zhparser`，不可用时保留按库缓存 BM25。
6. **阈值策略**：`retrieval_min_score`、`rerank_min_score` 可在系统设置中配置；低分时明确“不知道”。

#### 验收标准

- 追问“那它需要什么材料”能结合上一轮改写成完整问题。
- Rerank 开启后，评估集 Hit@5 不下降，MRR 提升。
- 关闭 Embedding 服务时，BM25 仍可返回结果并标注降级。
- 10 万 chunk 下，单次检索 P95 不超过 1.5 秒（不含 LLM）。

### E8 知识运营（P1）

#### 规则

1. **知识缺口雷达**：收集无答案、低分、点踩问题，聚类后展示主题、示例问题、出现次数、趋势。
2. 管理员可标记 `待补充/待更新/无需处理/已解决`，并关联到文件或知识库。
3. **检索调试台**：输入问题，展示改写后 query、向量结果、BM25 结果、Rerank 结果、最终上下文和分数。
4. **使用看板**：问答量、活跃用户、知识库使用排名、Top 问题、无答案率、点踩率、P95 延迟、token 成本、入库失败数。
5. **知识健康度**：过期文档、重复文档、空分块、长期未命中、解析失败。

#### 验收标准

- 无答案问题在 5 分钟内进入缺口列表。
- 管理员可将缺口标记为已解决，并在补充文档后回放验证。
- 调试台能复现一次真实问答的召回链路。

### E9 开放与生态（P2）

- 连接器：飞书/钉钉/Confluence/SharePoint/对象存储，先选 1 个。
- OpenAI 兼容 `/v1/chat/completions`，支持流式与引用返回。
- MCP Server：把“知识库检索/问答”暴露为工具。
- 嵌入式问答组件：iframe/JS SDK。
- Agentic RAG：意图路由（闲聊/知识库/表格/工具）、最多 3 步、超时降级。

## 6. 数据模型变更

### 6.1 新增/修改表

```sql
-- 用户与权限
ALTER TABLE users ADD COLUMN department VARCHAR(128);
ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;

ALTER TABLE knowledge_bases ADD COLUMN visibility VARCHAR(16) DEFAULT 'public';
ALTER TABLE knowledge_bases ADD COLUMN owner_id INTEGER REFERENCES users(id);

CREATE TABLE kb_members (
  id SERIAL PRIMARY KEY,
  kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission VARCHAR(16) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (kb_id, user_id)
);

CREATE TABLE kb_departments (
  id SERIAL PRIMARY KEY,
  kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  department VARCHAR(128) NOT NULL,
  UNIQUE (kb_id, department)
);

-- 入库任务与版本
CREATE TABLE file_versions (
  id SERIAL PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  storage_path VARCHAR(512) NOT NULL,
  checksum VARCHAR(64),
  size BIGINT DEFAULT 0,
  status VARCHAR(16) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (file_id, version)
);

CREATE TABLE ingestion_jobs (
  id SERIAL PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  file_version INTEGER NOT NULL,
  stage VARCHAR(16) NOT NULL,
  progress INTEGER DEFAULT 0,
  attempts INTEGER DEFAULT 0,
  status VARCHAR(16) NOT NULL,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  started_at TIMESTAMP,
  finished_at TIMESTAMP
);

ALTER TABLE files ADD COLUMN active_version INTEGER DEFAULT 1;
ALTER TABLE files ADD COLUMN checksum VARCHAR(64);

ALTER TABLE chunks ADD COLUMN version_id INTEGER REFERENCES file_versions(id);
ALTER TABLE chunks ADD COLUMN heading_path VARCHAR(512);
ALTER TABLE chunks ADD COLUMN token_count INTEGER DEFAULT 0;
ALTER TABLE chunks ADD COLUMN char_start INTEGER;
ALTER TABLE chunks ADD COLUMN char_end INTEGER;

ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE;
ALTER TABLE conversations ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();

ALTER TABLE messages ADD COLUMN status VARCHAR(16) DEFAULT 'complete';
ALTER TABLE messages ADD COLUMN error_message TEXT;

-- 反馈
CREATE TABLE message_feedback (
  id SERIAL PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating VARCHAR(8) NOT NULL,
  reason VARCHAR(32),
  comment TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (message_id, user_id)
);

-- 审计补充
ALTER TABLE audit_logs ADD COLUMN ip VARCHAR(64);
ALTER TABLE audit_logs ADD COLUMN user_agent VARCHAR(255);
ALTER TABLE audit_logs ADD COLUMN result VARCHAR(16) DEFAULT 'success';

-- 系统设置补充
ALTER TABLE system_settings ADD COLUMN retrieval_min_score FLOAT DEFAULT 0.5;
ALTER TABLE system_settings ADD COLUMN rerank_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE system_settings ADD COLUMN rerank_top_n INTEGER DEFAULT 20;
ALTER TABLE system_settings ADD COLUMN query_rewrite_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE system_settings ADD COLUMN max_history_messages INTEGER DEFAULT 20;
ALTER TABLE system_settings ADD COLUMN summary_trigger_messages INTEGER DEFAULT 30;
ALTER TABLE system_settings ADD COLUMN chat_rate_limit_per_minute INTEGER DEFAULT 10;
```

### 6.2 索引

```sql
CREATE INDEX idx_files_kb_id ON files(kb_id);
CREATE INDEX idx_chunks_file_id ON chunks(file_id);
CREATE INDEX idx_chunks_version_id ON chunks(version_id);
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_ingestion_jobs_status ON ingestion_jobs(status);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
```

### 6.3 兼容策略

- 使用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 做轻量迁移，保持现有部署可升级。
- `chunks.version_id` 允许为空，旧数据回填到 `file_versions` 的 v1。
- `messages.sources` 先兼容旧 JSON 字符串格式，新增字段缺省处理。
- 迁移前自动备份 `pg_dump`，并提供回滚 SQL。

## 7. API 变更

### 7.1 权限

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/knowledge-bases` | 只返回当前用户可见的库 |
| PUT | `/api/knowledge-bases/{id}/visibility` | 设置 public/department/private |
| GET/POST/DELETE | `/api/knowledge-bases/{id}/members` | 成员管理 |
| GET/POST/DELETE | `/api/knowledge-bases/{id}/departments` | 部门授权 |

### 7.2 文件与任务

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/files` | 返回 `file_id`、`job_id`、`status` |
| GET | `/api/files?kb_id=&page=&page_size=` | 分页 |
| GET | `/api/files/{id}/job` | 当前任务进度与错误 |
| POST | `/api/files/{id}/retry` | 重试失败任务 |
| POST | `/api/files/{id}/cancel` | 取消排队任务 |
| GET | `/api/files/{id}/versions` | 版本列表 |
| POST | `/api/files/{id}/rollback` | 回滚到指定版本 |
| GET | `/api/chunks/{chunk_id}` | 单个分块详情 |

### 7.3 对话

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/conversations?page=&page_size=&q=` | 分页/搜索 |
| PATCH | `/api/conversations/{id}` | 重命名/置顶 |
| GET | `/api/conversations/{id}/messages?page=&page_size=` | 分页 |
| POST | `/api/conversations/{id}/chat` | SSE，`start` 带 `generation_id` |
| POST | `/api/conversations/{id}/stop` | 停止当前生成 |
| POST | `/api/conversations/{id}/regenerate` | 重新生成最后一条回答 |
| POST | `/api/messages/{id}/feedback` | 点赞/点踩 |
| GET | `/api/conversations/{id}/export` | 导出 Markdown |

### 7.4 管理与运营

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit-logs?action=&operator=&from=&to=&page=` | 审计查询 |
| GET | `/api/analytics/overview` | 使用概览 |
| GET | `/api/analytics/gaps` | 知识缺口列表 |
| PATCH | `/api/analytics/gaps/{id}` | 标记缺口状态 |
| POST | `/api/debug/retrieval` | 检索调试，仅管理员 |
| GET | `/api/health/live` | 进程存活 |
| GET | `/api/health/ready` | 依赖就绪 |

## 8. 非功能需求

| 类别 | 要求 |
|---|---|
| 性能 | 检索 P95 ≤ 1.5s（不含 LLM）；首 token P95 ≤ 3s；列表接口 P95 ≤ 500ms |
| 容量 | 单库 10 万 chunk、100 并发登录用户可用 |
| 可用性 | 单机部署目标 99.5%；任务可恢复；失败可重试 |
| 安全 | 权限检索前过滤；密码强度；登录/问答限流；审计覆盖敏感操作 |
| 兼容 | 现有 md/txt/docx/pdf 文件、现有会话、现有 pgvector 数据可平滑升级 |
| 可观测 | 结构化日志、请求 ID、检索链路记录、健康检查、关键指标 |
| 可维护 | 新功能按 router/service/schema 分层；每个 P0 功能有测试 |

## 9. 验收与上线

### 9.1 功能验收

- P0 的 E1-E6 验收标准全部通过；P1 的 E7-E8 在试运行前通过；E9 按实际启用范围验收。
- P0 回归用例覆盖：登录、权限、上传、更新失败回滚、引用打开、停止生成、限流。
- 现有 21 个测试保持通过；新增测试不少于 20 个。

### 9.2 数据验收

- 迁移脚本在现有数据库副本上执行成功。
- 旧文件、旧分块、旧会话可正常读取。
- 旧引用能显示，缺失字段有降级展示。

### 9.3 上线方式

1. 预发环境跑迁移 + 回归。
2. 生产先备份数据库与 uploads。
3. 低峰期发布，保留上一版本镜像。
4. 观察 24 小时：错误率、P95 延迟、入库失败率、无答案率。
5. 异常时回滚镜像 + 执行回滚 SQL。

## 10. 待确认问题

1. 部门数据来源：手工维护，还是接公司组织架构/LDAP？
2. 文档版本保留：最近 2 个版本，还是固定 30 天？
3. Rerank 部署：本地 TEI/Xinference，还是云服务？服务器是否有 GPU？
4. PostgreSQL 是否允许安装 `pg_jieba`/`zhparser`？不允许时是否接受“按库缓存 BM25”？
5. 连接器优先级：飞书、钉钉、Confluence、SharePoint 先做哪个？
6. 是否要求首次登录强制改密？
7. 问答限流默认值是否符合公司使用习惯？
