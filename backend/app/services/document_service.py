from pathlib import Path

import re
import xml.etree.ElementTree as ET
import zipfile

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_community.document_loaders import PyMuPDFLoader, TextLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_DIR, settings
from app.models import Chunk, FileRecord
from app.services.settings_service import get_system_settings

SUPPORTED_TYPES = {"md", "docx", "pdf", "txt"}


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url,
        client_kwargs={"trust_env": False},
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name="knowledge",
        embedding_function=get_embeddings(),
        persist_directory=str(BASE_DIR / settings.chroma_dir),
    )


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _load_docx(path: Path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{WORD_NS}body")
    blocks: list[str] = []
    if body is None:
        return []
    for element in body:
        if element.tag == f"{WORD_NS}p":
            text = "".join(node.text or "" for node in element.iter(f"{WORD_NS}t")).strip()
            if text:
                blocks.append(text)
        elif element.tag == f"{WORD_NS}tbl":
            rows: list[list[str]] = []
            for row in element.findall(f"{WORD_NS}tr"):
                cells = [
                    "".join(node.text or "" for node in cell.iter(f"{WORD_NS}t")).strip()
                    for cell in row.findall(f"{WORD_NS}tc")
                ]
                if cells:
                    rows.append(cells)
            if not rows:
                continue
            width = max(len(row) for row in rows)
            lines = [
                "| " + " | ".join(row + [""] * (width - len(row))) + " |"
                for row in rows
            ]
            lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
            blocks.append("\n".join(lines))
    return [Document(page_content="\n\n".join(blocks))]


def _load_documents(path: Path, file_type: str):
    if file_type == "md":
        return TextLoader(str(path), encoding="utf-8").load()
    if file_type == "txt":
        return TextLoader(str(path), encoding="utf-8").load()
    if file_type == "docx":
        return _load_docx(path)
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
                table_rows = _split_table_rows(block)
                grouped: list[str] = []
                current: list[str] = []
                current_size = 0
                for row in table_rows:
                    if current and current_size + len(row) > chunk_size:
                        grouped.append("\n\n".join(current))
                        current = []
                        current_size = 0
                    current.append(row)
                    current_size += len(row)
                if current:
                    grouped.append("\n\n".join(current))
                chunks.extend(Document(page_content=item, metadata=doc.metadata) for item in grouped)
            else:
                chunks.extend(splitter.split_documents([Document(page_content=block.strip(), metadata=doc.metadata)]))
    return chunks


async def ingest_file(
    db: AsyncSession, file_id: int, path: Path, file_type: str, filename: str, kb_id: int | None = None
) -> int:
    docs = _load_documents(path, file_type)
    system_settings = await get_system_settings(db)
    chunks = _split_documents(
        docs, system_settings.chunk_size, system_settings.chunk_overlap
    )
    if not chunks:
        return 0

    texts, metadatas, ids = [], [], []
    for index, chunk in enumerate(chunks):
        page_no = int(chunk.metadata.get("page") or 0)
        db.add(
            Chunk(file_id=file_id, chunk_index=index, page_no=page_no, content=chunk.page_content)
        )
        texts.append(chunk.page_content)
        metadatas.append(
            {
                "kb_id": str(kb_id) if kb_id else "",
                "file_id": str(file_id),
                "chunk_index": index,
                "source": filename,
                "page": page_no,
            }
        )
        ids.append(f"{file_id}_{index}")
    await db.flush()
    get_vectorstore().add_texts(texts=texts, metadatas=metadatas, ids=ids)
    return len(chunks)


async def delete_file_vectors(db: AsyncSession, file_id: int) -> None:
    result = await db.execute(select(Chunk).where(Chunk.file_id == file_id))
    rows = result.scalars().all()
    if not rows:
        return
    get_vectorstore().delete(ids=[f"{file_id}_{row.chunk_index}" for row in rows])
    for row in rows:
        await db.delete(row)


async def reindex_missing_kb(db: AsyncSession) -> int:
    """旧版本向量缺少 kb_id 元数据时，按文件重建向量（升级时执行一次）。"""
    vectorstore = get_vectorstore()
    data = vectorstore.get(include=["metadatas"]) or {}
    metadatas = data.get("metadatas") or []
    if metadatas and all("kb_id" in (meta or {}) for meta in metadatas):
        return 0

    records = (await db.execute(select(FileRecord))).scalars().all()
    upload_dir = BASE_DIR / settings.upload_dir
    rebuilt = 0
    for record in records:
        await delete_file_vectors(db, record.id)
        matches = list(upload_dir.glob(f"{record.id}_*"))
        if not matches:
            continue
        rebuilt += await ingest_file(
            db, record.id, matches[0], record.file_type, record.filename, record.kb_id
        )
    await db.commit()
    return rebuilt
