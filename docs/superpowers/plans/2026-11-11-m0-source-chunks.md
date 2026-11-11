# M0-6 引用按块加载执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. 当前会话实施，独立代理审查计划和结果；不自动提交或推送。

**Goal:** 完成单分块查询、引用弹窗按需加载、缓存/错误状态处理和既有引用格式兼容，避免文件更新后错误展示其他内容。

**Architecture:** 使用现有 `Chunk.id` 和 `FileRecord.version`，不新增表列或迁移。新引用保存 chunk_id、file_id、file_version；单块接口核对文件与版本。弹窗不长期缓存全文，每次打开只查询所需片段；缺少精确定位信息的旧引用仅展示保存的摘要并说明限制，不猜测当前 chunk_index。

**Tech Stack:** 现有 FastAPI/SQLAlchemy、Vue 3、pytest、Node 内置测试，无新增依赖、外部服务或配置变更。

## 规则与边界

- 新增登录保护的 `GET /api/chunks/{chunk_id}?file_id=<预期文件>&version=<引用版本>`，返回单个片段正文、文件信息、版本、页码；响应 `Cache-Control: no-store`。
- 文件已更新返回 410，文件/分块删除或不属于预期文件返回 404；未登录 401。当前全员共享知识库的访问规则保持，M1 再增加成员权限。
- 检索向量 SQL 与 BM25 ORM 查询均补充 chunk_id、file_version，经过 RAG 来源、流式事件、持久化消息完整保留。新来源按文件 ID/版本分组，同名文件不混合。
- 新引用打开必须携带三项定位信息；若返回的身份/版本与引用不符，不展示该正文。更新失败而原版本仍保留时，可继续查看旧有效分块。
- 不保留跨弹窗打开的全文缓存。每次打开重取单块，避免永久缓存无法感知更新/删除。旧格式不再请求整个文件所有分块。
- 兼容当前 grouped excerpts 对象、早期 excerpts 字符串、早期平铺 source/page 对象。缺少 chunk_id/版本时显示快照摘要和“历史引用未保存精确位置”；完全没有摘要时显示清晰说明。格式异常不得让整段历史打不开。
- 弹窗逐片段显示加载中、加载失败、失效和重试入口。单个请求失败不妨碍其他片段；快速切换或关闭弹窗后的迟到响应不能覆盖当前弹窗。
- 不承诺恢复已被删除的历史全文，完整版本留存/回滚仍属于 M2/M3；本批不做索引/分页或 ACL 迁移。

## 文件职责

| 文件 | 变动 |
| --- | --- |
| `backend/app/routers/chunks.py` | 新增单片段读取、身份/版本校验和缓存响应头 |
| `backend/app/schemas.py`、`main.py` | 单片段响应模型及路由注册 |
| `backend/app/services/retrieval_service.py` | 两路检索补充稳定定位元数据 |
| `backend/app/services/rag_service.py` | 来源携带 ID/版本及文件类型、库名 |
| `backend/app/routers/chat.py` | 按文件身份分组，保存及发送定位字段 |
| `frontend/src/views/ChatView.vue` | 格式兼容、单块加载、每项状态和重试、移除永久缓存 |
| `backend/tests/test_chunks.py`、`test_sources.py`、`test_chat.py` | 单块接口、元数据链路、同名来源持久化回归 |
| `frontend/tests/SourceDialog.spec.js` | 单块请求、加载/失败/重试、更新删除重开、旧格式和迟到响应 |
| `docs/变更记录.md`、本计划、`docs/二阶段迭代计划.md` | 验证记录和 M0-6 进度 |

## Task 1：单分块查询接口

- [x] 1.1 先写测试并确认失败：登录与普通用户访问、仅返回目标块、不返回向量、缺块/删文件 404、版本更新 410、错误文件 ID 拒绝、旧版本处理中仍可读、Cache-Control。
- [x] 1.2 实现 `ChunkDetailOut` 和独立 chunks 路由，查询目标分块/文件，核对预期身份与版本；不改已有文件管理批量分块接口。
- [x] 1.3 运行单块接口测试确认通过。

## Task 2：新引用稳定定位链路

- [x] 2.1 先写失败回归，验证向量与 BM25 元数据包含 chunk_id/file_version，RAG 构造来源保留字段，SSE 与数据库 sources 保存字段，同名文件分组独立。
- [x] 2.2 修改检索查询和 `_row_document`；RAG 来源转发元数据。chat 分组键包含文件 ID/版本，组及 excerpt 均保存定位信息，保留已有 text/index 字段。
- [x] 2.3 运行元数据与 chat 回归，正常问答使用 FakeGraph/FakeLLM，不调用真实模型。

## Task 3：弹窗按需加载与旧引用兼容

- [x] 3.1 先补前端失败测试：只请求 /chunks/{id}、加载中状态、失败/重试、再次打开必须重取、更新/删除不展示旧缓存或其他正文、旧字符串及平铺引用、快速切换/关闭。
- [x] 3.2 移除 chunkCache 和整份文件读取；在实际打开时规范化来源，逐项请求单块并校验返回身份，逐项 catch/finally，失败时保留摘要并显示说明。
- [x] 3.3 新旧来源统一成可展示格式，在历史读取与 SSE 来源接收处应用；坏 sources JSON 不影响聊天正文。
- [x] 3.4 使用现有主题变量与 Element Plus 组件补加载态、状态提示和单项重试。请求闭包绑定本次 items，不让旧请求覆盖新弹窗；401 沿用已实现的清凭证跳登录。
- [x] 3.5 运行所有前端逻辑测试与构建。

## Task 4：联调、审查与记录

- [x] 4.1 后端全量 pytest、前端 Node tests/build、修改文件内存语法编译及 diff --check。
- [x] 4.2 独立只读审查：重点核对元数据完整性、文件更新/删除后的旧引用、旧格式降级、缓存和弹窗请求竞争。
- [x] 4.3 如本地服务可用，重启后端并创建严格标记的临时数据，真实浏览器验证新引用全文、旧引用摘要、更新失效/删除提示和重试；不调用真实模型、不改原账号密码；结束后定向清理。
- [x] 4.4 更新进度与变更记录，记录本轮覆盖和限制；未授权前不提交推送。

## 验证命令

```powershell
# backend/
.\.venv\Scripts\python.exe -B -m pytest tests/test_chunks.py tests/test_sources.py tests/test_chat.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
# frontend/
node --test tests/*.spec.js
npm run build
```

基线：后端 96 passed、2 skipped；前端逻辑 29 passed。默认不启用真实检索集成测试；不增加测试依赖，沿用已验证的项目 Python 3.13 执行方式。

## 执行结果（2026-11-11）

- 先运行新增回归，后端定向测试 10 项失败、前端引用测试 14 项失败，均确认对应未实现行为；实现后后端全量 **108 passed、2 skipped**，前端全量 **43 passed**。
- `npm run build` 成功；9 个修改 Python 模块内存语法编译通过；`git diff --check` 通过。现有依赖弃用和前端大包提示保持。
- 同一个独立代理先审查计划，再只读审查最终改动，结论 Approved，无待修复重要问题。
- 本地 PostgreSQL/pgvector 验证单块接口只返回目标正文、不返回向量、`no-store`，真实向量 SQL 保留定位元数据；未调用模型或向量模型服务。
- 隔离内置浏览器以本轮临时账号登录，验证新引用完整原文、旧对象摘要、字符串摘要及平铺来源无摘要提示；更新临时文档后同一引用显示 `410` 失效，删除后显示 `404`，重试正常结束且不显示其他版本正文。
- 后端实际日志确认每次仅请求 `/api/chunks/{id}?file_id=...&version=...`，没有读取整份文件的分块；真实接口/浏览器验证记录截图位于本地 `output/playwright/m0-source-*.png`。
- 已退出临时浏览器账号并定向清理本轮测试用户、库、文件/分块、会话及消息；原 Chrome 管理员登录保留。前后端和 PostgreSQL 保持运行。
- 不恢复未保存的历史全文；两个真实模型检索集成测试保持跳过。本轮未提交、推送或发布。
