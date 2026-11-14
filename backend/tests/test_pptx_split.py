import pytest
from pptx import Presentation
from pptx.util import Pt

from app.services.document_service import _load_pptx, _split_docx


def _build_pptx(path, slides):
    """slides: list of dict(title, texts=[...], table=[[...]...] or None, notes=str or None)"""
    prs = Presentation()
    for spec in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1])  # 标题+内容版式（含 title 与 idx 1 正文占位符）
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


def test_page_title_breadcrumb(split_pptx):
    chunks = split_pptx(
        [
            {"title": "XQ-300 简介", "texts": ["XQ-300 是一款高精度校准仪器，支持多通道同步采集。" * 5]},
            {"title": "校准流程", "texts": ["校准需按标准流程执行，先预热再逐点校准。" * 5]},
        ]
    )
    assert chunks[0].page_content.startswith("第1页 · XQ-300 简介")
    assert chunks[1].page_content.startswith("第2页 · 校准流程")


def test_table_row_grouping(split_pptx):
    chunks = split_pptx(
        [
            {
                "title": "维护计划",
                "table": [["项目", "周期"], ["整机校准", "每季度一次"]],
            }
        ]
    )
    text = chunks[0].page_content
    assert "项目: 整机校准" in text
    assert "周期: 每季度一次" in text


def test_notes_included(split_pptx):
    chunks = split_pptx(
        [
            {"title": "安全须知", "texts": ["操作前必须佩戴防护装备并确认接地良好。" * 5], "notes": "仅限内部使用"},
        ]
    )
    assert any("【备注】仅限内部使用" in c.page_content for c in chunks)


def test_missing_title_fallback(split_pptx):
    chunks = split_pptx([{"title": "", "texts": ["本页没有标题但内容足够长，用于验证回退行为。" * 5]}])
    assert chunks[0].page_content.startswith("第1页 · 未命名")


def test_empty_slide_skipped(split_pptx):
    chunks = split_pptx(
        [
            {"title": "空页"},
            {"title": "有内容页", "texts": ["这一页包含实际内容，不会被跳过。" * 10]},
        ]
    )
    assert all("空页" not in c.page_content for c in chunks)
    # 页码按物理页编号：空页被跳过后，内容页保留自己的真实页码
    assert any(c.page_content.startswith("第2页 · 有内容页") for c in chunks)
    assert not any(c.page_content.startswith("第1页") for c in chunks)


def test_lead_in_with_table_same_chunk(split_pptx):
    chunks = split_pptx(
        [
            {
                "title": "配置参数",
                "texts": ["配置如下："],
                "table": [["参数", "取值"], ["采样率", "1kHz"], ["量程", "±10V"]],
            }
        ]
    )
    assert len(chunks) == 1
    text = chunks[0].page_content
    assert "配置如下：" in text
    assert "参数: 采样率" in text
    assert "参数: 量程" in text


def test_short_slides_merged_keep_both_prefixes(split_pptx):
    chunks = split_pptx(
        [
            {"title": "摘要", "texts": ["短句内容。" * 10]},
            {"title": "结论", "texts": ["短句内容。" * 10]},
        ]
    )
    assert len(chunks) == 1
    text = chunks[0].page_content
    assert text.startswith("第1页 · 摘要")
    assert "第2页 · 结论" in text
    assert len(text) >= 100  # 合并后不产生 <100 字碎片
