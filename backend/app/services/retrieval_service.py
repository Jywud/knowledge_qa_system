import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from sqlalchemy import select, text

from app.models import Chunk, FileRecord, KnowledgeBase
from app.services.document_service import get_embeddings
from app.config import settings

CHINESE_STOP_CHARS = set("的了在是我有和就不人都一为大上个子中会说要到你们会着没好给这那也时等与及或对其把被让从向而并但因此于由之一二三四五六七八九十什么吗呢吧啊哪些")


def tokenize_for_search(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    return [token for token in tokens if token not in CHINESE_STOP_CHARS]


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


async def _vector_search(query_vector: list[float], kb_id: int | None, limit: int) -> list[Document]:
    from app.database import SessionLocal

    params: dict = {"qv": str(query_vector), "k": limit}
    statement = """
        SELECT c.file_id, c.chunk_index, c.page_no, c.content,
               f.kb_id, f.filename, f.file_type, f.created_at,
               kb.name AS kb_name
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        JOIN knowledge_bases kb ON kb.id = f.kb_id
        WHERE c.embedding IS NOT NULL
    """
    if kb_id:
        statement += " AND f.kb_id = :kb_id"
        params["kb_id"] = kb_id
    max_distance = 1 - settings.retrieval_min_score
    statement += " AND c.embedding <=> CAST(:qv AS vector) <= :max_distance"
    params["max_distance"] = max_distance
    statement += " ORDER BY c.embedding <=> CAST(:qv AS vector) LIMIT :k"

    async with SessionLocal() as db:
        result = await db.execute(text(statement), params)
        rows = result.all()
    return [_row_document(row) for row in rows]


def _bm25_search(query: str, rows: list, limit: int) -> list[Document]:
    documents = [_row_document(row) for row in rows]
    if not documents:
        return []

    retriever = BM25Retriever.from_documents(
        documents,
        preprocess_func=tokenize_for_search,
        k=limit,
    )
    query_tokens = tokenize_for_search(query)
    query_set = set(query_tokens)
    cjk_count = sum(1 for token in query_tokens if not token.isascii())
    required_overlap = min(3, cjk_count) if cjk_count else 1
    results = []
    for document in retriever.invoke(query):
        document_tokens = set(tokenize_for_search(document.page_content))
        if len(query_set & document_tokens) >= required_overlap:
            results.append(document)
    return results


async def hybrid_search(query: str, kb_id: int | None, top_k: int) -> list[Document]:
    from app.database import SessionLocal

    candidate_k = max(top_k * 2, 10)
    query_vector = await get_embeddings().aembed_query(query)
    vector_docs = await _vector_search(query_vector, kb_id, candidate_k)
    if not vector_docs:
        return []

    async with SessionLocal() as db:
        sql_statement = (
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
            sql_statement = sql_statement.where(FileRecord.kb_id == kb_id)
        result = await db.execute(sql_statement)
        rows = result.all()

    keyword_docs = _bm25_search(query, rows, candidate_k)
    return _merge_candidates(vector_docs, keyword_docs, top_k)
