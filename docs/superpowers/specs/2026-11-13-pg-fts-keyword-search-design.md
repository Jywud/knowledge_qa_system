# 关键词检索 PostgreSQL 全文检索化设计（zhparser）

状态：方案已经用户确认（直接实施原设计稿的方案 B，跳过内存缓存过渡）；三个技术分叉按用户确认的推荐执行。本文取代 [关键词检索优化设计](../../关键词检索优化设计.md) 的方案 B 章节，并修正其中两处：不采用 `content_tsv` 生成列（见"数据与索引"），过渡方案 A 不再实施。

## 目标与非目标

目标：

1. 关键词检索从"每请求全量加载 chunk 进内存重建 BM25"改为 PostgreSQL 全文检索（GIN 索引），查询成本与 chunk 总量解耦。
2. 中文分词从单字切分升级为 zhparser 词级分词，提升术语、型号类查询的召回质量。
3. `hybrid_search` 对外签名、返回 Document 的 metadata 字段、`_chunk_key`（`(file_id, chunk_index)`）全部不变；RRF 融合与向量检索逻辑不动。

非目标：高可用/多实例、限流外置、SSO、监控、外置搜索引擎（Elasticsearch 等）、检索评测基准建设。本次只动关键词检索通道及其部署前提。

## 部署形态

- 新增自建 PostgreSQL 镜像 Dockerfile（基于 `pgvector/pgvector:pg16`，多阶段构建），编译固定版本的 SCWS 与 zhparser。
- `docker-compose.yml` 的 `db` 服务换用该镜像。
- 本机开发库 `my-postgres` 容器基于新镜像重建，复用 `postgres_data` 卷，数据保留（用户已确认）。
- zhparser 的 SCWS 源地址、编译参数、GUC 名称与默认值在撰写本设计时无法在线核验（当前环境访问不了 GitHub）；**镜像构建成功 + `CREATE EXTENSION zhparser` 成功即为核验门槛**，实现计划第一步就是构建镜像并实测分词效果，发现与本文假设不符时以实测为准并回改本文。

## 数据与索引

不新增列。原设计稿的 `content_tsv` 生成列方案废弃，理由：生成列写进 `models.py` 会让 `create_all` 在 SQLite 测试套件里报错（SQLite 无 `to_tsvector`），要么违反"新增列两处同步"的项目规则，要么引入方言分支；表达式索引则完全避开此问题，且与现有 HNSW 索引同模式维护。

lifespan 建库顺序（全部幂等，可重复执行）：

1. `CREATE EXTENSION IF NOT EXISTS vector`（现状）
2. `CREATE EXTENSION IF NOT EXISTS zhparser`
3. 创建文本检索配置 `zh`（parser = zhparser，映射实词词性到 simple；具体映射清单与 `zhparser.punctuation_ignore`、`zhparser.multi_short` 等 GUC 以镜像内实测为准），已存在则跳过
4. `create_all`、HNSW 索引（现状）
5. `CREATE INDEX IF NOT EXISTS idx_chunks_content_fts ON chunks USING GIN (to_tsvector('zh'::regconfig, content))`

zhparser 扩展或配置创建失败：记录明确错误日志并继续启动（与"向量补齐失败不阻断启动"同一哲学），关键词通道随后按"降级"路径工作。**注意**：调整 zhparser GUC 或分词映射后，表达式索引语义随之改变，需 `REINDEX`；此点写入运维说明。

## 检索链路

新增 `_fts_search(query, kb_id, kb_ids, user_id, limit)`，与 `_vector_search` 同构：

- 相同的权限谓词（system_admin 直通 / `role_knowledge_bases` EXISTS）、kb 过滤、`_require_context` 校验；异常降级不扩大授权范围。
- 相同的返回列集，复用 `_row_document`。
- 查询构造：`plainto_tsquery('zh', query)`（AND 语义，要求分出的词全部命中）；零命中时改用分词结果 OR 连接的 tsquery 重查，按 `ts_rank` 降序取 limit 条。AND 与 OR 兜底都在 SQL 内完成，分词经由文本检索配置获得，不在 Python 侧再做分词。

`hybrid_search` 重构：

- 删除全量 rows 查询、`_bm25_search`、`tokenize_for_search`、`CHINESE_STOP_CHARS`；`rank_bm25` 依赖与 `langchain_community` BM25Retriever 引用一并移除（`tokenize_for_search` 若被其他模块引用，实施时 grep 确认后处理）。
- 融合逻辑不变：向量与 FTS 各取 `candidate_k`（`max(top_k*2, 10)`）候选，RRF（k=60）融合取 `top_k`。
- 降级语义（与现状对齐，只换通道）：
  - 向量异常（embedding 服务失败等）→ 纯 FTS 结果；
  - FTS 异常（扩展缺失等）→ 纯向量结果，记日志；
  - 向量正常但零命中（全部低于阈值）→ 仍直接返回空，**不**用 FTS 兜底（保留现有"向量空即空"的保守行为）；
  - 两通道都异常 → 空列表。

已知取舍：`ts_rank` 排序精度低于 BM25，由向量通道与 RRF 融合兜底；关键词通道的职责是精确命中（型号、编号、人名、术语）。

## 运维任务（非代码）

- 企业术语、产品名分不出来时维护 zhparser 自定义词典；词典变更同样需要 REINDEX。
- 换用带 zhparser 的自建镜像是正式部署的硬前提，README 部署章节需写明。

## 生态对照（选型依据）

主流开源 RAG 平台的关键词检索路线：RAGFlow 用外置 Elasticsearch 系倒排 + BM25（引擎抽象可换）；Dify 把全文检索委托给向量数据库原生能力（Weaviate BM25F、Qdrant BM25 稀疏向量），另有 jieba 分词 + 应用侧 BM25 关键词表的"经济模式"；LangChain/LlamaIndex 参考实现即本系统改造前的内存 BM25。它们不选 PG 扩展路线的原因是产品形态假设不同——多后端产品不能假设用户装得了扩展。

本系统是刻意的单 Postgres 栈，zhparser 编译进自建镜像保持该性质，与社区多年的 PG 中文全文检索实践一致。演进出口：若未来迁移到无法安装扩展的托管 PG（云 RDS），`_fts_search` 是唯一替换点，可换为 Dify 式"应用侧 jieba 分词 + 简单配置 tsvector"方案，`hybrid_search` 与融合逻辑不动。

## 测试

- 默认套件（SQLite 内存库）保持"不需要 PostgreSQL"的承诺：FTS 关键词通道与向量通道同样以打桩方式处理；实施时检查现有涉及 `hybrid_search` 的测试（如检索权限、多库对话）的桩点并适配。
- 新增门控的 PostgreSQL 测试（仿 `test_roles_postgres.py` 的随机 schema 隔离模式，独立环境变量启用）：中文词级命中、AND→OR 兜底触发、权限谓词过滤（无权限库内容不出现）、`_chunk_key` 稳定性、FTS 异常降级仅向量、向量异常降级仅 FTS。
- 真实检索回归 `RUN_RETRIEVAL_TESTS=1` 按现状执行；按 AGENTS.md 在 PR 中记录人工测试问题与期望来源。
- 人工验证：上传含产品型号与自定义术语的文档 → 提问可命中；知识库未命中时如实说明；删除文件后立即不再命中（同事务一致性天然保证）。

## 验收

1. 代码中不再存在"无 limit 读取全部 chunk"的检索路径；FTS 查询 `EXPLAIN` 显示走 GIN 索引（Bitmap Index Scan），非 Seq Scan。
2. 默认测试套件全部通过；门控 Postgres FTS 测试通过；`npm run build` 前端不受影响（无改动）。
3. `docker compose up -d --build` 全链路可用，compose `db` 使用自建镜像。
4. 文档同步：README 混合检索与部署章节、CLAUDE.md 混合检索与已知取舍章节、`docs/关键词检索优化设计.md` 标注已实施。
