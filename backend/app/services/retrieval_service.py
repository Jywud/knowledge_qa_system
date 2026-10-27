import math
import re

from langchain_community.retrievers import BM25Retriever

from langchain_core.documents import Document
from sqlalchemy import select

from app.models import Chunk, FileRecord, KnowledgeBase


def tokenize_for_search(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def _bm25_search(query: str, rows: list, limit: int) -> list[Document]:
    documents = [_row_document(row) for row in rows]
    if not documents:
        return []

    retriever = BM25Retriever.from_documents(
        documents,
        preprocess_func=tokenize_for_search,
        k=limit,
    )
    return retriever.invoke(query)


def _row_document(row) -> Document:
    return Document(
        page_content=row.content,
        metadata={
            "kb_id": str(row.kb_id),
            "file_id": str(row.file_id),
            "chunk_index": str(row.chunk_index),
            "source": row.filename,
            "page": row.page_no,
            "file_type": row.file_type,
            "kb_name": row.kb_name,
            "uploaded_at": row.created_at.isoformat(timespec="seconds")
            if row.created_at
            else "",
        },
    )


def _chunk_key(document: Document) -> tuple[str, str]:
    metadata = document.metadata
    return str(metadata.get("file_id", "")), str(metadata.get("chunk_index", ""))


def _merge_candidates(vector_docs: list[Document], keyword_docs: list[Document], limit: int):
    scores: dict[tuple[str, str], float] = {}
    docs: dict[tuple[str, str], Document] = {}

    for candidates in (vector_docs, keyword_docs):
        for rank, document in enumerate(candidates, start=1):
            key = _chunk_key(document)
            scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
            docs.setdefault(key, document)

    ordered_keys = sorted(scores, key=lambda key: (-scores[key], key))
    return [docs[key] for key in ordered_keys[:limit]]


async def hybrid_search(query: str, kb_id: int | None, top_k: int, vectorstore) -> list[Document]:
    from app.database import SessionLocal

    candidate_k = max(top_k * 2, 10)
    async with SessionLocal() as db:
        statement = (
            select(
                Chunk.file_id,
                Chunk.chunk_index,
                Chunk.page_no,
                Chunk.content,
                FileRecord.kb_id,
                FileRecord.filename,
                FileRecord.file_type,
                FileRecord.created_at,
                KnowledgeBase.name.label("kb_name"),
            )
            .join(FileRecord, FileRecord.id == Chunk.file_id)
            .join(KnowledgeBase, KnowledgeBase.id == FileRecord.kb_id)
            .order_by(Chunk.id)
        )
        if kb_id:
            statement = statement.where(FileRecord.kb_id == kb_id)
        result = await db.execute(statement)
        rows = result.all()

    chunk_map = {(str(row.file_id), str(row.chunk_index)): row for row in rows}
    keyword_docs = _bm25_search(query, rows, candidate_k)

    if kb_id:
        vector_docs = vectorstore.similarity_search(
            query, k=candidate_k, filter={"kb_id": str(kb_id)}
        )
    else:
        vector_docs = vectorstore.similarity_search(query, k=candidate_k)

    for document in vector_docs:
        row = chunk_map.get(_chunk_key(document))
        if not row:
            continue
        document.metadata.update(
            {
                "file_type": row.file_type,
                "kb_name": row.kb_name,
                "uploaded_at": row.created_at.isoformat(timespec="seconds")
                if row.created_at
                else "",
            }
        )

    return _merge_candidates(vector_docs, keyword_docs, top_k)
