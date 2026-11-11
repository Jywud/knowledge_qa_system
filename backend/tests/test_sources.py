from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from app.models import Chunk, FileRecord
from app.services import retrieval_service
from app.services.rag_service import make_chat_node


def test_row_document_keeps_stable_reference_identity():
    row = SimpleNamespace(chunk_id=10, file_id=1, chunk_index=0, content="正文", kb_id=1,
                          filename="guide.md", file_type="md", page_no=0, file_version=3,
                          kb_name="测试库", created_at=datetime(2026, 11, 11))
    doc = retrieval_service._row_document(row)
    assert str(doc.metadata["chunk_id"]) == "10"
    assert doc.metadata["file_version"] == 3


async def test_keyword_retrieval_keeps_reference_identity(test_db, monkeypatch):
    async with test_db() as db:
        record = FileRecord(kb_id=1, filename="guide.md", file_type="md", uploaded_by=1, version=3)
        db.add(record)
        await db.flush()
        chunk = Chunk(file_id=record.id, chunk_index=0, content="needle reference document")
        db.add(chunk)
        await db.commit()
        chunk_id = chunk.id
    provider = SimpleNamespace(aembed_query=AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: provider)
    docs = await retrieval_service.hybrid_search("needle", 1, 5)
    assert len(docs) == 1
    assert str(docs[0].metadata["chunk_id"]) == str(chunk_id)
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
    docs = await retrieval_service._vector_search([0.1], 1, 5)
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
    result = await make_chat_node(llm)({"messages": [HumanMessage(content="问题")], "kb_id": "1"})
    source = result["sources"][0]
    assert source["chunk_id"] == "10" and source["file_version"] == 3
    assert source["file_id"] == "1" and source["file_type"] == "md" and source["kb_name"] == "测试库"
