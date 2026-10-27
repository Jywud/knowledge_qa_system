# docx 切分优化设计

## 背景

当前 docx 切分按"空行分段、段落即 chunk"，存在三个质量问题：

1. 标题、单行步骤等短段落各自成 chunk，语义不完整（如"一、目前已有的MCP服务："单独命中）。
2. 同一内容在文档中出现多次时产生重复 chunk，浪费检索 topK 名额。
3. chunk 之间没有章节上下文，检索命中后无法判断所属主题。

## 方案

### 解析升级：python-docx 替换手写 XML

- 新增依赖 `python-docx`（轻量成熟），替换 `document_service` 中的手写 zipfile/XML 解析。
- 按文档顺序遍历段落与表格（python-docx 需通过 body 子元素顺序迭代）。
- 每个段落识别是否为标题：
  1. 样式名以 `Heading` 开头（`Heading 1` → 一级）。
  2. 兜底读段落 `outlineLvl` 大纲级别。

### 切分策略：标题感知

1. 以标题为界把文档切成章节，标题层级维护章节路径（如 `使用指南 > MCP 配置`）。
2. 章节内的连续普通段落合并成组，超过 chunk_size 才用 `RecursiveCharacterTextSplitter` 切分——短段落天然归并，不再产生碎片 chunk。
3. 章节内的表格仍走现有"表格逐行展开"逻辑，不被长文切分器生硬切断。
4. 每个 chunk 的内容前拼接章节路径（breadcrumb），提升检索语义并让来源可读。
5. 只有标题没有内容的章节跳过。

### 同文件去重

入库前对同一文件的 chunk 按内容去重，重复段落只保留一条（章节路径参与内容，不同章节的同文本不会被误删）。

md / txt / pdf 的切分逻辑本次不变。

## 存量数据处理

切分策略变更不影响已入库数据。已有 docx 文件需**删除后重新上传**以获得新切分效果；不做自动重建。

## 改动范围

| 文件 | 改动 |
| --- | --- |
| `backend/requirements.txt` | 新增 `python-docx` |
| `backend/app/services/document_service.py` | docx 解析与切分重写；ingest 增加同文件去重 |
| `backend/tests/test_docx_split.py` | 新增切分单测 |

## 验证方式

1. 单测：构造含标题/短段落/重复段落/表格的 docx，断言标题不孤立成 chunk、重复内容被去重、breadcrumb 存在。
2. 手动：重新上传 MCP 对接指南.docx，查看分块，确认来源1/2 不再重复、标题段落已归并。
