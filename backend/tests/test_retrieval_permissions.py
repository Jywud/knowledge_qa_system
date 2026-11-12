from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models import Chunk, FileRecord, KnowledgeBase
from app.services import retrieval_service


async def test_retrieval_requires_authenticated_context(test_db, monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    with pytest.raises(HTTPException):
        await retrieval_service.hybrid_search("needle", 1, 5)


async def test_keyword_fallback_never_reads_ungranted_library(test_db, monkeypatch):
    async with test_db() as db:
        kb = KnowledgeBase(name="secret", created_by=1)
        db.add(kb)
        await db.flush()
        for kb_id in [1, kb.id]:
            file = FileRecord(kb_id=kb_id, filename=f"{kb_id}.md", file_type="md", uploaded_by=1)
            db.add(file)
            await db.flush()
            db.add(Chunk(file_id=file.id, chunk_index=0, content="needle source document"))
        await db.commit()
        secret_id = kb.id
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    visible = await retrieval_service.hybrid_search("needle", 1, 5, user_id=2)
    assert len(visible) == 1 and visible[0].metadata["kb_id"] == "1"
    hidden = await retrieval_service.hybrid_search("needle", secret_id, 5, user_id=2)
    assert hidden == []
