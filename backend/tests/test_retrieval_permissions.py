from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from app.services import retrieval_service


async def test_retrieval_requires_authenticated_context(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    with pytest.raises(HTTPException):
        await retrieval_service.hybrid_search("needle", 1, 5)


async def test_conflicting_scope_short_circuits_before_channels(test_db, monkeypatch):
    embed = AsyncMock(side_effect=RuntimeError("不应触发向量通道"))
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(aembed_query=embed))
    fts = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval_service, "_fts_search", fts)
    assert await retrieval_service.hybrid_search("needle", 1, 5, user_id=2, kb_ids=[2]) == []
    embed.assert_not_awaited()
    fts.assert_not_awaited()


async def test_vector_failure_falls_back_to_keyword_channel(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    doc = Document(page_content="needle source document",
                   metadata={"chunk_id": "7", "file_id": "1", "chunk_index": "0", "file_version": 1})

    async def fake_fts(query, kb_id, limit, *, user_id=None, kb_ids=None):
        assert kb_id == 1 and user_id == 2
        return [doc]

    monkeypatch.setattr(retrieval_service, "_fts_search", fake_fts)
    docs = await retrieval_service.hybrid_search("needle", 1, 5, user_id=2)
    assert [d.metadata["chunk_id"] for d in docs] == ["7"]
    assert docs[0].metadata["file_version"] == 1
