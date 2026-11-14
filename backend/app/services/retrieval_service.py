import logging

from langchain_core.documents import Document
from sqlalchemy import text
from fastapi import HTTPException

from app.services.document_service import get_embeddings
from app.services.rerank_service import rerank_documents
from app.config import settings

logger = logging.getLogger(__name__)


def _row_document(row) -> Document:
    return Document(
        page_content=row.content,
        metadata={
            "chunk_id": str(row.chunk_id),
            "kb_id": str(row.kb_id),
            "file_id": str(row.file_id),
            "file_version": row.file_version,
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


def _require_context(kb_id: int | None, user_id: int | None, kb_ids: list[int] | None = None) -> None:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise HTTPException(401, "检索缺少认证用户")
    if kb_id is not None and (type(kb_id) is not int or kb_id <= 0):
        raise HTTPException(400, "知识库范围无效")
    if kb_ids is not None and (not isinstance(kb_ids, list) or not kb_ids or any(
        type(value) is not int or value <= 0 for value in kb_ids
    )):
        raise HTTPException(400, "会话检索范围无效")


async def _vector_search(query_vector: list[float], kb_id: int | None, limit: int, *, user_id: int | None = None,
                         kb_ids: list[int] | None = None, min_score: float | None = None) -> list[Document]:
    from app.database import SessionLocal

    _require_context(kb_id, user_id, kb_ids)
    params: dict = {"qv": str(query_vector), "k": limit, "user_id": user_id}
    # 与 FTS_PERMISSION 保持同步（审查备注：两份谓词仅靠评审对齐，演进时先合并）
    statement = """
        SELECT c.id AS chunk_id, c.file_id, c.chunk_index, c.page_no, c.content,
               f.kb_id, f.filename, f.file_type, f.created_at, f.version AS file_version,
               kb.name AS kb_name
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        JOIN knowledge_bases kb ON kb.id = f.kb_id
        WHERE c.embedding IS NOT NULL
          AND (EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                       WHERE ur.user_id = :user_id AND r.system_key = 'system_admin')
               OR EXISTS (SELECT 1 FROM user_roles ur JOIN role_knowledge_bases rk ON rk.role_id = ur.role_id
                          WHERE ur.user_id = :user_id AND rk.kb_id = f.kb_id))
    """
    if kb_id:
        statement += " AND f.kb_id = :kb_id"
        params["kb_id"] = kb_id
    if kb_ids is not None:
        statement += " AND f.kb_id = ANY(CAST(:kb_ids AS INTEGER[]))"
        params["kb_ids"] = kb_ids
    max_distance = 1 - (settings.retrieval_min_score if min_score is None else min_score)
    statement += " AND c.embedding <=> CAST(:qv AS vector) <= :max_distance"
    params["max_distance"] = max_distance
    statement += " ORDER BY c.embedding <=> CAST(:qv AS vector) LIMIT :k"

    async with SessionLocal() as db:
        result = await db.execute(text(statement), params)
        rows = result.all()
    return [_row_document(row) for row in rows]


FTS_PERMISSION = """
    (EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
             WHERE ur.user_id = :user_id AND r.system_key = 'system_admin')
     OR EXISTS (SELECT 1 FROM user_roles ur JOIN role_knowledge_bases rk ON rk.role_id = ur.role_id
                WHERE ur.user_id = :user_id AND rk.kb_id = f.kb_id))
"""

_AND_TSQUERY = "plainto_tsquery('zh'::regconfig, :q)"


async def _fts_search(query: str, kb_id: int | None, limit: int, *, user_id: int | None = None,
                      kb_ids: list[int] | None = None) -> list[Document]:
    """zhparser 词级全文检索；AND 零命中时以分词 OR 组合兜底并按 ts_rank 排序。"""
    from app.database import SessionLocal

    _require_context(kb_id, user_id, kb_ids)
    params: dict = {"user_id": user_id, "k": limit, "q": query}
    statement = f"""
        SELECT c.id AS chunk_id, c.file_id, c.chunk_index, c.page_no, c.content,
               f.kb_id, f.filename, f.file_type, f.created_at, f.version AS file_version,
               kb.name AS kb_name
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        JOIN knowledge_bases kb ON kb.id = f.kb_id
        WHERE {FTS_PERMISSION}
          AND to_tsvector('zh'::regconfig, c.content) @@ {_AND_TSQUERY}
    """
    if kb_id:
        statement += " AND f.kb_id = :kb_id"
        params["kb_id"] = kb_id
    if kb_ids is not None:
        statement += " AND f.kb_id = ANY(CAST(:kb_ids AS INTEGER[]))"
        params["kb_ids"] = kb_ids
    statement += (" ORDER BY ts_rank(to_tsvector('zh'::regconfig, c.content), "
                  f"{_AND_TSQUERY}) DESC, c.id LIMIT :k")

    async with SessionLocal() as db:
        rows = (await db.execute(text(statement), params)).all()
        if rows:
            return [_row_document(row) for row in rows]

        # AND 零命中：用 zhparser 自身分词结果构造 OR 查询；词面加引号防 tsquery 操作符注入
        lexemes = (await db.execute(text(
            "SELECT DISTINCT lexeme FROM unnest(to_tsvector('zh'::regconfig, :q)) "
            "ORDER BY lexeme"), {"q": query})).scalars().all()
        if not lexemes:
            return []
        or_params = dict(params)
        or_params.pop("q", None)
        or_params["or_query"] = " | ".join("'" + lex.replace("'", "''") + "'" for lex in lexemes)
        or_statement = statement.replace(
            _AND_TSQUERY, "to_tsquery('zh'::regconfig, :or_query)")
        rows = (await db.execute(text(or_statement), or_params)).all()
    return [_row_document(row) for row in rows]


async def hybrid_search(query: str, kb_id: int | None, top_k: int, *, rrf_top_n: int | None = None,
                        rerank_enabled: bool = False, top_n: int | None = None, min_score: float | None = None,
                        user_id: int | None = None, kb_ids: list[int] | None = None) -> list[Document]:
    """混合检索：top_k 为每路召回候选数，rrf_top_n 为 RRF 融合后保留条数，min_score 为向量召回相关度下限；
    开启 rerank 时对融合候选精排并取 top_n 条，失败按融合顺序降级。"""
    _require_context(kb_id, user_id, kb_ids)
    if kb_id is not None and kb_ids is not None and kb_id not in kb_ids:
        return []
    keep = rrf_top_n or top_k
    try:
        query_vector = await get_embeddings().aembed_query(query)
        vector_docs = await _vector_search(query_vector, kb_id, top_k, user_id=user_id, kb_ids=kb_ids,
                                           min_score=min_score)
    except Exception:
        logger.exception("向量检索失败，降级为纯关键词结果")
        vector_docs = None
    if vector_docs is not None and not vector_docs:
        return []  # 保守行为保持：向量零命中直接返回空，不引入关键词噪声
    try:
        keyword_docs = await _fts_search(query, kb_id, top_k, user_id=user_id, kb_ids=kb_ids)
    except Exception:
        logger.exception("关键词检索失败，降级为纯向量结果")
        keyword_docs = []
    fused = _merge_candidates(vector_docs, keyword_docs, keep) if vector_docs is not None \
        else keyword_docs[:keep]
    if not rerank_enabled:
        return fused
    return await _rerank_candidates(query, fused, top_n or keep)


async def _rerank_candidates(query: str, docs: list[Document], top_n: int) -> list[Document]:
    if not docs:
        return docs
    try:
        results = await rerank_documents(query, [doc.page_content for doc in docs], top_n)
    except Exception:
        logger.exception("重排服务调用失败，按融合顺序返回前 %s 条", top_n)
        return docs[:top_n]
    ordered = [docs[index] for index, _score in results if 0 <= index < len(docs)]
    return ordered[:top_n]
