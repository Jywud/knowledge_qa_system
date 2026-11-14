from pathlib import Path

import logging
import re

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from langchain_core.documents import Document
from langchain_community.document_loaders import PyMuPDFLoader, TextLoader
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_DIR, settings
from app.models import Chunk, FileRecord
from app.services.settings_service import get_system_settings

SUPPORTED_TYPES = {"md", "docx", "pdf", "txt"}
# 短于此字符数（含面包屑）的分块会在切分后并入相邻分块，避免 embedding 信号过弱
_MIN_CHUNK_CHARS = 100
logger = logging.getLogger(__name__)


def get_embeddings() -> OllamaEmbeddings | OpenAIEmbeddings:
    if settings.embed_provider == "openai":
        if not settings.embed_openai_api_key:
            raise RuntimeError("EMBED_OPENAI_API_KEY 未配置，请在 backend/.env 中填写")
        kwargs = {
            "model": settings.embed_model,
            "api_key": settings.embed_openai_api_key,
            "base_url": settings.embed_openai_base_url,
            "check_embedding_ctx_length": False,
        }
        if settings.embed_openai_dimensions is not None:
            kwargs["dimensions"] = settings.embed_openai_dimensions
        return OpenAIEmbeddings(**kwargs)
    if settings.embed_provider != "ollama":
        raise RuntimeError("EMBED_PROVIDER 仅支持 ollama 或 openai")

    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url,
        client_kwargs={"trust_env": False},
    )


def _iter_docx_blocks(doc):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


def _heading_level(paragraph) -> int | None:
    style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
    if style_name.startswith("heading"):
        try:
            return int(style_name.split()[-1])
        except ValueError:
            return 1
    p_pr = paragraph._p.pPr
    if p_pr is not None:
        outline = p_pr.find(qn("w:outlineLvl"))
        if outline is not None:
            return int(outline.get(qn("w:val"))) + 1
    return None


def _table_to_markdown(table) -> str:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)


def _load_docx(path: Path) -> list:
    doc = DocxDocument(str(path))
    blocks = []
    for item in _iter_docx_blocks(doc):
        if isinstance(item, DocxParagraph):
            text = item.text.strip()
            if not text:
                continue
            level = _heading_level(item)
            if level:
                blocks.append(("heading", text, level))
            else:
                blocks.append(("paragraph", text, None))
        else:
            markdown = _table_to_markdown(item)
            if markdown:
                blocks.append(("table", markdown, None))
    return blocks


def _group_table_rows(block: str, chunk_size: int) -> list[str]:
    table_rows = _split_table_rows(block)
    grouped: list[str] = []
    current: list[str] = []
    current_size = 0
    for row in table_rows:
        if current and current_size + len(row) > chunk_size:
            grouped.append("\n\n".join(current))
            # 从第二组起带上前一组的最后一行，跨组边界保留一行重叠上下文
            current = [current[-1]]
            current_size = len(current[0])
        current.append(row)
        current_size += len(row)
    if current:
        grouped.append("\n\n".join(current))
    return grouped


def _merge_small_chunks(chunks: list[Document], chunk_size: int) -> list[Document]:
    """过短分块就近合并：同节并入前一个分块（面包屑去重），跨节的小节起始块并入后一个分块。

    合并后总长不得超过 chunk_size 的 1.2 倍，两边都放不下则保留原样；
    从前往后线性扫描，合并产生的较大块不再作为短块参与后续判断。
    """
    limit = int(chunk_size * 1.2)
    merged: list[Document] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        if len(chunk.page_content) >= _MIN_CHUNK_CHARS:
            merged.append(chunk)
            index += 1
            continue
        label = chunk.metadata.get("path_label") or ""
        prefix = f"{label}\n" if label else ""
        body = chunk.page_content[len(prefix):] if prefix and chunk.page_content.startswith(prefix) else chunk.page_content
        same_section = bool(merged) and merged[-1].metadata.get("path_label") == chunk.metadata.get("path_label")
        if same_section:
            prev = merged[-1]
            if len(prev.page_content) + 1 + len(body) <= limit:
                merged[-1] = Document(
                    page_content=f"{prev.page_content}\n{body}", metadata=dict(prev.metadata)
                )
                index += 1
                continue
        elif index + 1 < len(chunks):
            following = chunks[index + 1]
            candidate = f"{chunk.page_content}\n{following.page_content}"
            if len(candidate) <= limit:
                merged.append(
                    Document(page_content=candidate, metadata=dict(following.metadata))
                )
                index += 2
                continue
        merged.append(chunk)
        index += 1
    return merged


def _split_docx(blocks: list, chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    sections: list[tuple[str, list]] = []
    heading_path: list[tuple[int, str]] = []
    current_blocks: list = []

    def flush_section():
        if current_blocks:
            path_label = " > ".join(title for _, title in heading_path)
            sections.append((path_label, list(current_blocks)))
            current_blocks.clear()

    for kind, content, level in blocks:
        if kind == "heading":
            flush_section()
            while heading_path and heading_path[-1][0] >= level:
                heading_path.pop()
            heading_path.append((level, content))
        else:
            current_blocks.append((kind, content))
    flush_section()

    documents: list[Document] = []
    for path_label, section_blocks in sections:
        if not section_blocks:
            continue
        chunks: list[str] = []
        paragraph_buffer: list[str] = []

        def flush_paragraphs():
            if paragraph_buffer:
                chunks.extend(splitter.split_text("\n\n".join(paragraph_buffer)))
                paragraph_buffer.clear()

        block_index = 0
        while block_index < len(section_blocks):
            kind, content = section_blocks[block_index]
            following = section_blocks[block_index + 1] if block_index + 1 < len(section_blocks) else None
            if (
                kind == "paragraph"
                and content.rstrip().endswith(("：", ":"))
                and following is not None
                and following[0] == "table"
            ):
                # 引导句并入紧邻表格的开头，随首个行组走；连续多段只合并紧邻的那一段
                grouped = _group_table_rows(following[1], chunk_size)
                if grouped:
                    flush_paragraphs()
                    grouped[0] = f"{content}\n\n{grouped[0]}"
                    chunks.extend(grouped)
                    block_index += 2
                    continue
            if kind == "table":
                flush_paragraphs()
                chunks.extend(_group_table_rows(content, chunk_size))
            else:
                paragraph_buffer.append(content)
            block_index += 1
        flush_paragraphs()

        prefix = f"{path_label}\n" if path_label else ""
        documents.extend(
            Document(page_content=prefix + chunk, metadata={"path_label": path_label})
            for chunk in chunks
        )
    return _merge_small_chunks(documents, chunk_size)


def _load_documents(path: Path, file_type: str):
    if file_type == "md":
        return TextLoader(str(path), encoding="utf-8").load()
    if file_type == "txt":
        return TextLoader(str(path), encoding="utf-8").load()
    if file_type == "pdf":
        return PyMuPDFLoader(str(path), extract_tables="markdown").load()
    raise ValueError(f"不支持的文件类型: {file_type}")


def _split_table_rows(block: str) -> list[str]:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    if len(headers) < 2:
        return []
    rows = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        pairs = [f"{header}: {cell}" for header, cell in zip(headers, cells) if cell]
        if pairs:
            rows.append("\n".join(pairs))
    return rows


def _split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks: list[Document] = []
    for doc in docs:
        for block in re.split(r"\n\s*\n", doc.page_content):
            lines = [line for line in block.splitlines() if line.strip()]
            if len(lines) >= 3 and all("|" in line for line in lines) and "---" in lines[1]:
                grouped = _group_table_rows(block, chunk_size)
                chunks.extend(Document(page_content=item, metadata=doc.metadata) for item in grouped)
            else:
                chunks.extend(splitter.split_documents([Document(page_content=block.strip(), metadata=doc.metadata)]))
    return _merge_small_chunks(chunks, chunk_size)


async def ingest_file(
    db: AsyncSession, file_id: int, path: Path, file_type: str, filename: str, kb_id: int | None = None
) -> int:
    system_settings = await get_system_settings(db)
    if file_type == "docx":
        chunks = _split_docx(_load_docx(path), system_settings.chunk_size, system_settings.chunk_overlap)
    else:
        docs = _load_documents(path, file_type)
        chunks = _split_documents(docs, system_settings.chunk_size, system_settings.chunk_overlap)
    unique_chunks: list[Document] = []
    seen_contents: set[str] = set()
    for chunk in chunks:
        key = chunk.page_content.strip()
        if key and key not in seen_contents:
            seen_contents.add(key)
            unique_chunks.append(chunk)
    chunks = unique_chunks
    if not chunks:
        return 0

    texts: list[str] = []
    rows: list[Chunk] = []
    for index, chunk in enumerate(chunks):
        page_no = int(chunk.metadata.get("page") or 0)
        row = Chunk(
            file_id=file_id, chunk_index=index, page_no=page_no, content=chunk.page_content
        )
        db.add(row)
        rows.append(row)
        texts.append(chunk.page_content)
    await db.flush()
    vectors = await get_embeddings().aembed_documents(texts)
    if len(vectors) != len(rows):
        raise ValueError("向量数量与文档分块数量不一致")
    for row, vector in zip(rows, vectors):
        row.embedding = vector
    return len(chunks)


async def process_file_record(
    file_id: int, path: Path, file_type: str, filename: str, kb_id: int | None
) -> None:
    from app.database import SessionLocal

    try:
        async with SessionLocal() as db:
            await ingest_file(db, file_id, path, file_type, filename, kb_id)
            record = await db.get(FileRecord, file_id)
            if record:
                record.status = "ready"
            await db.commit()
    except Exception as exc:
        async with SessionLocal() as db:
            await db.execute(delete(Chunk).where(Chunk.file_id == file_id))
            record = await db.get(FileRecord, file_id)
            if record:
                record.status = "failed"
                record.status_message = str(exc)[:255]
            await db.commit()


def _uploaded_paths(upload_dir: Path, file_id: int) -> list[Path]:
    return [
        path
        for directory in (upload_dir, upload_dir / ".versions")
        for path in directory.glob(f"{file_id}_*")
        if path.is_file()
    ]


def _remove_upload(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("无法清理上传文件 %s", path, exc_info=True)


def delete_file_uploads(upload_dir: Path, file_id: int) -> None:
    """清理该文件的遗留及版本文件，不影响其他文件或暂存任务。"""
    for path in _uploaded_paths(upload_dir, file_id):
        _remove_upload(path)


async def process_file_update(
    file_id: int, path: Path, file_type: str, filename: str, size: int, expected_version: int
) -> None:
    """新分块和元数据一起提交；失败时保留可用的旧版本。"""
    from app.database import SessionLocal

    upload_dir = path.parent.parent  # 更新文件只来自 uploads/.pending。
    destination = upload_dir / ".versions" / f"{file_id}_v{expected_version + 1}_{filename}"
    previous_paths: list[Path] = []
    moved = False
    committed = False
    try:
        async with SessionLocal() as db:
            record = await db.get(FileRecord, file_id, with_for_update=True)
            if not record or record.version != expected_version or record.status != "processing":
                return
            previous_paths = _uploaded_paths(upload_dir, file_id)
            await delete_file_vectors(db, file_id)
            chunk_count = await ingest_file(db, file_id, path, file_type, filename, record.kb_id)
            if not chunk_count:
                raise ValueError("新文件没有可用内容")
            destination.parent.mkdir(exist_ok=True)
            path.replace(destination)
            moved = True
            record.filename = filename
            record.file_type = file_type
            record.size = size
            record.version = expected_version + 1
            record.status = "ready"
            record.status_message = None
            await db.commit()
            committed = True
    except Exception as exc:
        # COMMIT 可能已成功但回包失败，必须重新核实，不能直接删除新原件。
        try:
            async with SessionLocal() as db:
                record = await db.get(FileRecord, file_id, with_for_update=True)
                if record and record.version > expected_version:
                    committed = True
                else:
                    if moved:
                        _remove_upload(destination)
                    if record and record.version == expected_version and record.status == "processing":
                        chunk_count = await db.scalar(
                            select(func.count(Chunk.id)).where(Chunk.file_id == file_id)
                        )
                        record.status = "ready" if chunk_count else "failed"
                        record.status_message = f"更新失败，已保留原版本：{exc}"[:255]
                        await db.commit()
        except Exception:
            logger.exception("文件 %s 更新状态核实失败，保留磁盘文件以免丢失数据", file_id)
    finally:
        _remove_upload(path)

    if committed:
        # 只删除本次事务开始时见到的旧文件，不匹配之后并发更新生成的文件。
        for old_path in previous_paths:
            if old_path != destination:
                _remove_upload(old_path)


async def delete_file_vectors(db: AsyncSession, file_id: int) -> None:
    await db.execute(delete(Chunk).where(Chunk.file_id == file_id))
    await db.flush()


async def reindex_missing_embeddings(db: AsyncSession) -> int:
    """升级后缺失向量的文件按原始上传文件重建向量（启动时执行）。"""
    result = await db.execute(
        select(FileRecord.id)
        .join(Chunk, Chunk.file_id == FileRecord.id)
        .where(Chunk.embedding.is_(None))
        .distinct()
        .order_by(FileRecord.id)
    )
    file_ids = result.scalars().all()
    await db.rollback()
    if not file_ids:
        return 0

    upload_dir = BASE_DIR / settings.upload_dir
    rebuilt = 0
    for file_id in file_ids:
        try:
            record = await db.get(FileRecord, file_id)
            if record is None:
                await db.rollback()
                continue
            current_path = upload_dir / ".versions" / f"{file_id}_v{record.version}_{record.filename}"
            if not current_path.is_file():
                current_path = upload_dir / f"{file_id}_{record.filename}"
            if not current_path.is_file():
                await db.rollback()
                continue
            await delete_file_vectors(db, file_id)
            count = await ingest_file(
                db, file_id, current_path, record.file_type, record.filename, record.kb_id
            )
            if count == 0:
                raise ValueError("重建未产生有效分块，保留原分块")
            await db.commit()
            rebuilt += count
        except Exception:
            await db.rollback()
            logger.exception("文件 %s 启动向量重建失败，保留原分块并继续", file_id)
    return rebuilt
