# pgvector 迁移设计

## 背景

迁移前使用 ChromaDB 存储向量，chunk 元数据在 PostgreSQL，两个存储需要手动同步。当前已迁移到 pgvector，向量与业务数据在一个数据库中管理；以下方案补充了 2026-11-11 的启动异常隔离行为。

## 目标

1. 向量存储迁移到现有 PostgreSQL（pgvector 扩展），删除 ChromaDB 依赖。
2. chunk 内容与向量同表同事务，删除/更新文件不再有双存储同步问题。
3. 检索链路保持不变：向量检索 + BM25 + RRF 融合。
4. 旧数据（已上传文件）启动时自动重建向量，避免升级后检索失效。

## 方案设计

### 存储结构

- Docker 镜像从 `postgres:16-alpine` 改为 `pgvector/pgvector:pg16`（内置 pgvector 扩展）。
- 应用启动时执行 `CREATE EXTENSION IF NOT EXISTS vector`。
- `chunks` 表新增一列：

```sql
embedding vector(1024)
```

维度由环境变量 `EMBED_DIM` 控制（默认 1024，对应 bge-m3）。存量库通过 `ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)` 平滑升级。

### 写入流程（上传 / 更新文件）

1. 解析文档并按现有策略切分。
2. 将所有 chunk 写入 `chunks` 表（此时 `embedding` 为 NULL）。
3. 调用 Ollama 批量生成向量（`aembed_documents`），回填到对应 chunk 行。
4. 同一事务提交，向量缺失时文件仍在但检索不到，不会产生外部孤儿数据。

### 删除流程

直接删除 `chunks` 行（删除文件时级联删除），不再需要清理外部向量库。

### 检索流程

- 向量检索：原生 SQL 使用 pgvector 距离运算符

```sql
ORDER BY chunks.embedding <=> CAST(:query_vector AS vector) LIMIT :k
```

支持 `kb_id` 过滤，与现有 BM25 的 SQL 过滤保持一致。
- BM25：保持现有 LangChain `BM25Retriever` 实现不变。
- 融合：保持现有 RRF 实现不变。

### 兼容与数据迁移

- 应用启动时检查 `chunks` 中 `embedding IS NULL` 且文件仍存在于上传目录的记录，按文件重新解析、切分并向量化（复用现有 ingest 逻辑）。
- 每文件独立提交；失败回滚并保留旧块，记录日志后继续其他文件。补齐顶层异常不单独阻断应用启动，数据库与 Checkpoint 初始化仍须成功。恢复模型服务后可重启重试，尚无持久化重试队列。
- ChromaDB 相关目录（`chroma_data/`）迁移完成后可手动删除。

## 改动范围

| 文件 | 改动 |
| --- | --- |
| `docker-compose.yml` | 镜像换为 pgvector 版 Postgres；删除 Chroma 卷与环境变量 |
| `backend/requirements.txt` | 移除 `chromadb`、`langchain-chroma`；新增 `pgvector` |
| `backend/app/models.py` | `Chunk` 新增 `embedding` 列 |
| `backend/app/main.py` | 启动时创建扩展、补列、重建缺失向量；移除 Chroma 重建逻辑 |
| `backend/app/services/document_service.py` | 切换为向量回填到 PG；移除 Chroma 客户端 |
| `backend/app/services/retrieval_service.py` | 向量检索改为 pgvector 原生 SQL |
| `backend/app/services/rag_service.py` | 移除 vectorstore 传参 |
| `backend/app/config.py` | 移除 `chroma_dir`；新增 `embed_dim` |
| `README.md` | 更新部署说明 |

## 风险与约束

1. 当前启动流程已创建 `idx_chunks_embedding_hnsw` 余弦距离索引；更大数据规模仍需实际查询计划与负载验证。
2. 更换 Embedding 模型或维度需要清空并重建向量。
3. 补齐缺失向量依赖所选 Embedding 服务可用；失败文件保留旧块，不会产生可检索的新向量。向量通道异常时可降级 BM25，但向量通道正常返回空结果时不会强制关键词兜底。

## 验证方式

1. `pytest`（SQLite 测试库，覆盖登录/用户/上传链路）。
2. 使用 pgvector Docker 镜像验证扩展创建、建表、向量写入、距离查询。
3. 手动验证：上传文件 → 查看分块 → 对话检索命中来源；删除文件后对话不再命中。
