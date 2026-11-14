# PPTX 文档支持实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上传 .pptx 幻灯片入库：按页切片（页标题作面包屑）、表格复用行分组、演讲者备注纳入索引。

**Architecture:** 新增 `_load_pptx` 产出与 `_load_docx` 完全相同的块元组流（`("heading"/"paragraph"/"table", text, level)`），直接复用 `_split_docx` 切片与 `_merge_small_chunks` 后处理——零新切片概念。接入点三处：`SUPPORTED_TYPES`、`ingest_file` 分发、前端 3 处 accept 属性。

**Tech Stack:** python-pptx（纯 OOXML 解析，新增依赖）；测试用 python-pptx 在 tmp_path 程序化构造 pptx fixture。

**范围决定（用户已确认）：** 只支持 pptx（旧版二进制 .ppt 不做，需 LibreOffice 转换层，重依赖不值）；演讲者备注纳入（段落块带「【备注】」前缀，引用可溯源到页）。分支 `feat/pptx-support`（已建）。

---

### Task 1: 依赖、_load_pptx 解析器、ingest 接入、上传白名单

**Files:**
- Modify: `backend/requirements.txt`（加 `python-pptx>=1.0`）
- Modify: `backend/app/services/document_service.py`（`SUPPORTED_TYPES`、`_load_pptx`、`ingest_file` 分发）
- Modify: `backend/tests/test_docx_split.py` 或新建 `backend/tests/test_pptx_split.py`（建议新文件，fixture 独立）

- [ ] **Step 1: 安装依赖并写入 requirements**

```bash
cd backend && ./.venv/Scripts/python -m pip install python-pptx
echo "python-pptx>=1.0" >> requirements.txt   # 手工插到 python-docx 附近，保持分组
```

验证：`./.venv/Scripts/python -c "import pptx; print(pptx.__version__)"` 无异常。

- [ ] **Step 2: 实现 _load_pptx（块流契约与 _load_docx 完全一致）**

在 `document_service.py` 的 `_load_docx` 之后新增（先读 `_table_to_markdown` 的函数体——若其对 `table.rows` / `row.cells` / `cell.text` 纯鸭子类型无 isinstance 检查，则直接复用；否则按下述写 pptx 专用变体 `_pptx_table_to_markdown`，输出格式保持 `| a | b |` 一致）：

```python
from pptx import Presentation


def _load_pptx(path: Path) -> list:
    blocks: list = []
    presentation = Presentation(str(path))
    for number, slide in enumerate(presentation.slides, start=1):
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip()
        heading_text = f"第{number}页 · {title or '未命名'}"
        slide_blocks: list = []
        for shape in slide.shapes:
            if getattr(shape, "has_table", False) and shape.has_table:
                markdown = _pptx_table_to_markdown(shape.table) if not _table_is_docx(shape.table) else _table_to_markdown(shape.table)
                if markdown.strip():
                    slide_blocks.append(("table", markdown, None))
            elif shape.has_text_frame and shape.text_frame.text.strip():
                slide_blocks.append(("paragraph", shape.text_frame.text.strip(), None))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                slide_blocks.append(("paragraph", f"【备注】{notes}", None))
        if not slide_blocks:
            continue  # 空页（无内容无备注）不产生任何块
        blocks.append(("heading", heading_text, 1))
        blocks.extend(slide_blocks)
    return blocks
```

实现注意：
- `_table_to_markdown` 兼容性以**实际函数体为准**：python-docx 与 python-pptx 的表都暴露 `.rows` / `row.cells` / `cell.text`，若现有实现纯鸭子类型则直接调用、删掉上面伪代码中的分支
- `shape.has_text_frame` 的判定顺序在 `has_table` 之后（表格 shape 也可能有 text_frame）
- 空页跳过可避免"仅面包屑的空块"与短块合并产生跨页粘连

- [ ] **Step 3: SUPPORTED_TYPES 与 ingest 分发**

```python
SUPPORTED_TYPES = {"md", "docx", "pdf", "txt", "pptx"}
```

`ingest_file` 的分发（现 :311）改为：

```python
    if file_type == "docx":
        chunks = _split_docx(_load_docx(path), system_settings.chunk_size, system_settings.chunk_overlap)
    elif file_type == "pptx":
        chunks = _split_docx(_load_pptx(path), system_settings.chunk_size, system_settings.chunk_overlap)
    else:
        docs = _load_documents(path, file_type)
        chunks = _split_documents(docs, system_settings.chunk_size, system_settings.chunk_overlap)
```

（`_split_docx` 实为通用块流切片器；改名留待后续，本次不做无关重命名。）

- [ ] **Step 4: 编译检查**

```bash
cd backend && ./.venv/Scripts/python -m py_compile app/services/document_service.py && ./.venv/Scripts/python -m pytest tests/ -q
```

预期：编译通过；全套件 176 passed / 9 skipped（此时 pptx 尚无用例，行为未变）。

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/services/document_service.py
git commit -m "feat: parse pptx into the shared block stream

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 测试（程序化构造 pptx fixture）

**Files:**
- Create: `backend/tests/test_pptx_split.py`

- [ ] **Step 1: 写 fixture 与用例（先红灯——Step 1 未实现前本文件无法全绿；若 Task 1 已先行实现则直接绿，跳过红灯环节并注明）**

fixture 用 python-pptx 在 tmp_path 构造真实 pptx（不 mock 解析器）：

```python
import pytest
from pptx import Presentation
from pptx.util import Pt

from app.services.document_service import _split_docx, _load_pptx


def _build_pptx(path, slides):
    """slides: list of dict(title, texts=[...], table=[[...]...] or None, notes=str or None)"""
    prs = Presentation()
    for spec in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[5])  # 标题+内容版式
        slide.shapes.title.text = spec["title"]
        body = slide.placeholders[1]
        tf = body.text_frame
        for i, text in enumerate(spec.get("texts", [])):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = text
        if spec.get("table"):
            rows, cols = len(spec["table"]), len(spec["table"][0])
            graphic = slide.shapes.add_table(rows, cols, Pt(0), Pt(0), Pt(400), Pt(200))
            for r, row in enumerate(spec["table"]):
                for c, value in enumerate(row):
                    graphic.table.cell(r, c).text = value
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]
    prs.save(path)


@pytest.fixture
def split_pptx(tmp_path):
    def _run(slides, chunk_size=800, chunk_overlap=100):
        path = tmp_path / "deck.pptx"
        _build_pptx(path, slides)
        return _split_docx(_load_pptx(path), chunk_size, chunk_overlap)
    return _run
```

用例（每条断言真实行为）：

1. **页标题面包屑**：两页（"XQ-300 简介"/"校准流程"）→ 每个内容分块 `startswith("第1页 · XQ-300 简介")` 或 `startswith("第2页 · 校准流程")`
2. **页内表格行分组**：一页含 2 行 2 列表格 → 分块含「表头: 单元格」形态的行对
3. **备注纳入**：带备注页 → 分块含 `【备注】` 且文本为备注原文
4. **无标题页回退**：title 传空 → 面包屑为「第N页 · 未命名」
5. **空页跳过**：无文本无表格无备注的页 → 不产生含该页面包屑的分块
6. **引导句+表格同页**：文本「配置如下：」+ 表格 → 引导句与行对同块（复用 docx 路径行为的回归确认）
7. **短页合并**：两页各只有一行短文本 → 短块合并后不产生 <100 字碎片（跨节保留双前缀）

- [ ] **Step 2: 运行**

```bash
cd backend && ./.venv/Scripts/python -m pytest tests/test_pptx_split.py -v
```

预期：7 passed（若 fixture 构造与 python-pptx 实际 API 有出入——如 layout 占位符索引、`has_table` 属性名——以实际报错为准修 fixture，不放松断言）。

- [ ] **Step 3: 全套件回归 + Commit**

```bash
cd backend && ./.venv/Scripts/python -m pytest tests/ -q    # 176+7=183 passed / 9 skipped 预期
git add backend/tests/test_pptx_split.py
git commit -m "test: pptx slide-level chunking coverage

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 前端上传类型提示 + 构建

**Files:**
- Modify: `frontend/src/views/FileManager.vue`（3 处 `accept=".md,.docx,.pdf,.txt"` → 追加 `,.pptx`）
- 核查 `frontend/src/views/HomeView.vue` 与文案中是否列了支持格式（grep `docx`），有则同步

- [ ] **Step 1: 修改 3 处 accept 属性 + 文案**
- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

预期：构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/FileManager.vue frontend/src/views/HomeView.vue
git commit -m "feat: accept pptx uploads in file manager

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 端到端验证（真实 pptx 走 API 链路）

- [ ] **Step 1: 程序化生成样例 pptx**（内容：XQ-300 校准周期每季度一次的表格 + 备注含「仅限内部使用」）到临时目录

- [ ] **Step 2: 重启 8000 后端**（当前进程代码不含 pptx 支持）——沿用 Start-Process 脱离会话方式；等 health ok

- [ ] **Step 3: API 链路**：登录 → 建临时库 → 上传 pptx → 等 ready → 限定该库提问「XQ-300 的校准周期是什么」→ 断言回答含「每季度」且来源含页码面包屑 → 问库外问题验证如实说明 → 清理会话与库 → 基线核对 files=3/chunks=23/kbs=2/conversations=1

- [ ] **Step 4: 若任何一步失败**：停止报 BLOCKED 附完整输出；不得伪造

---

### Task 5: 文档同步 + 合并

- [ ] **Step 1: README.md / README.en.md** 支持格式列表 `md / txt / docx / pdf` → 追加 pptx（两处：功能概览与使用流程若有提及）；`docs/变更记录.md` 新条目（含 Task 4 实测结果）；`CLAUDE.md` 文档摄取段落补一句 pptx 走块流复用
- [ ] **Step 2: Commit 文档 → master 合并（fast-forward）→ push → 删分支**（沿用切片分支的收尾模式）

---

## 验收标准

1. `.pptx` 上传入库成功：页标题面包屑、表格行分组、备注带【备注】前缀、空页跳过
2. `test_pptx_split.py` 7 passed；全套件无回归
3. 前端 accept 提示含 pptx，`npm run build` 通过
4. 端到端：真实 pptx 上传 → 提问 → 回答引用含页码面包屑；未命中如实说明
5. 文档与变更记录同步；分支合回 master 并推送
