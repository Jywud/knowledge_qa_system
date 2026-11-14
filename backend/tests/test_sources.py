from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from app.services import retrieval_service
from app.services.rag_service import make_chat_node


def test_row_document_keeps_stable_reference_identity():
    row = SimpleNamespace(chunk_id=10, file_id=1, chunk_index=0, content="正文", kb_id=1,
                          filename="guide.md", file_type="md", page_no=0, file_version=3,
                          kb_name="测试库", created_at=datetime(2026, 11, 11))
    doc = retrieval_service._row_document(row)
    assert str(doc.metadata["chunk_id"]) == "10"
    assert doc.metadata["file_version"] == 3


async def test_keyword_fallback_keeps_reference_identity(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    doc = Document(page_content="needle reference document",
                   metadata={"chunk_id": "7", "file_id": "1", "chunk_index": "0", "file_version": 3})

    async def fake_fts(query, kb_id, limit, *, user_id=None, kb_ids=None):
        return [doc]

    monkeypatch.setattr(retrieval_service, "_fts_search", fake_fts)
    docs = await retrieval_service.hybrid_search("needle", 1, 5, user_id=1)
    assert str(docs[0].metadata["chunk_id"]) == "7"
    assert docs[0].metadata["file_version"] == 3


async def test_vector_query_selects_reference_identity(monkeypatch):
    row = SimpleNamespace(chunk_id=10, file_id=1, chunk_index=0, content="正文", kb_id=1,
                          filename="guide.md", file_type="md", page_no=0, file_version=3,
                          kb_name="测试库", created_at=None)
    fake_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])))

    class Session:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("app.database.SessionLocal", Session)
    docs = await retrieval_service._vector_search([0.1], 1, 5, user_id=1)
    statement, params = fake_db.execute.await_args.args
    assert "c.id AS chunk_id" in str(statement)
    assert "f.version AS file_version" in str(statement)
    assert params["kb_id"] == 1
    assert str(docs[0].metadata["chunk_id"]) == "10"
    assert docs[0].metadata["file_version"] == 3


async def test_rag_sources_keep_reference_and_display_metadata(monkeypatch):
    doc = Document(page_content="原文内容", metadata={"chunk_id": "10", "file_id": "1",
        "file_version": 3, "chunk_index": "0", "source": "guide.md", "page": 0,
        "file_type": "md", "kb_name": "测试库"})
    monkeypatch.setattr("app.services.rag_service.hybrid_search", AsyncMock(return_value=[doc]))
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="回答[来源1]")))
    result = await make_chat_node(llm)({"messages": [HumanMessage(content="问题")], "kb_id": "1", "user_id": 1})
    source = result["sources"][0]
    assert source["chunk_id"] == "10" and source["file_version"] == 3
    assert source["file_id"] == "1" and source["file_type"] == "md" and source["kb_name"] == "测试库"
