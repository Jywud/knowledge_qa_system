import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.main import app
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, RoleKnowledgeBase
from app.services import retrieval_service


async def seed(client, test_db):
    async with test_db() as db:
        db.add_all([KnowledgeBase(id=2, name="第二授权库", created_by=1),
                    KnowledgeBase(id=3, name="未授权库", created_by=1)])
        await db.flush()
        db.add(RoleKnowledgeBase(role_id=2, kb_id=2))
        for kb_id in (1, 2, 3):
            file = FileRecord(kb_id=kb_id, filename="same.md", file_type="md", uploaded_by=1)
            db.add(file)
            await db.flush()
            db.add(Chunk(file_id=file.id, chunk_index=0, content="needle source document"))
        await db.commit()
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture
def graph(monkeypatch):
    class Graph:
        def __init__(self): self.calls = []
        async def astream(self, payload, **kwargs):
            self.calls.append(payload)
            yield AIMessageChunk(content="跨库回答"), {}
        async def aget_state(self, config): return SimpleNamespace(values={"sources": []})
    graph = Graph()
    monkeypatch.setattr(app.state, "graph", graph, raising=False)
    monkeypatch.setattr("app.routers.chat.generate_title", AsyncMock(return_value="跨库对话"))
    return graph


async def test_default_chat_uses_snapshot_of_all_authorized_kbs(client, test_db, graph):
    headers = await seed(client, test_db)
    response = await client.post("/api/conversations", headers=headers, json={})
    assert response.status_code == 200, response.text
    cid = response.json()["id"]
    assert response.json()["kb_id"] is None
    response = await client.post(f"/api/conversations/{cid}/chat", headers=headers, json={"content": "needle"})
    assert response.status_code == 200 and '"type": "error"' not in response.text
    assert graph.calls[0]["kb_id"] is None
    assert graph.calls[0]["kb_ids"] == [1, 2]
    async with test_db() as db:
        assert json.loads((await db.get(Conversation, cid)).kb_scope) == [1, 2]
    assert (await client.get(f"/api/conversations/{cid}/messages", headers=headers)).status_code == 200


async def test_revoking_one_library_hides_entire_multi_kb_history(client, admin_token, test_db, graph, monkeypatch):
    headers = await seed(client, test_db)
    created = await client.post("/api/conversations", headers=headers, json={})
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    await client.post(f"/api/conversations/{cid}/chat", headers=headers, json={"content": "needle"})
    changed = await client.put("/api/roles/2", headers={"Authorization": f"Bearer {admin_token}"},
                               json={"name": "测试角色", "kb_ids": [1]})
    assert changed.status_code == 200
    assert (await client.get("/api/conversations", headers=headers)).json() == []
    assert (await client.get(f"/api/conversations/{cid}/messages", headers=headers)).status_code == 404
    assert (await client.post(f"/api/conversations/{cid}/chat", headers=headers, json={"content": "继续"})).status_code == 404
    monkeypatch.setattr(app.state, "checkpointer", SimpleNamespace(adelete_thread=AsyncMock()), raising=False)
    assert (await client.delete(f"/api/conversations/{cid}", headers=headers)).status_code == 200


async def test_additional_grants_do_not_silently_expand_existing_conversation(client, admin_token, test_db, graph):
    headers = await seed(client, test_db)
    created = await client.post("/api/conversations", headers=headers, json={})
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    await client.put("/api/roles/2", headers={"Authorization": f"Bearer {admin_token}"},
                     json={"name": "测试角色", "kb_ids": [1, 2, 3]})
    response = await client.post(f"/api/conversations/{cid}/chat", headers=headers, json={"content": "needle"})
    assert response.status_code == 200
    assert graph.calls[0]["kb_ids"] == [1, 2]
    newer = await client.post("/api/conversations", headers=headers, json={})
    async with test_db() as db:
        assert json.loads((await db.get(Conversation, newer.json()["id"])).kb_scope) == [1, 2, 3]


@pytest.mark.parametrize("initial,target", [(None, 1), (1, None)])
async def test_cannot_switch_between_all_and_single_inside_conversation(client, test_db, initial, target):
    headers = await seed(client, test_db)
    created = await client.post("/api/conversations", headers=headers, json={"kb_id": initial})
    assert created.status_code == 200, created.text
    response = await client.post(f"/api/conversations/{created.json()['id']}/chat", headers=headers,
                                 json={"content": "needle", "kb_id": target})
    assert response.status_code == 400


async def test_all_scope_requires_at_least_one_readable_library(client, admin_token):
    response = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    await client.put("/api/roles/2", headers={"Authorization": f"Bearer {admin_token}"}, json={"name": "测试角色", "kb_ids": []})
    assert (await client.post("/api/conversations", headers=headers, json={})).status_code == 403


async def test_all_scope_keyword_fallback_passes_scope_and_snapshot(client, test_db, monkeypatch):
    await seed(client, test_db)
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(side_effect=RuntimeError("offline"))))
    fts = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval_service, "_fts_search", fts)
    assert await retrieval_service.hybrid_search("needle", None, 5, user_id=2, kb_ids=[1, 2, 3]) == []
    # hybrid_search 向关键词通道传 candidate_k = max(top_k * 2, 10)，此处 top_k=5 -> 10
    assert fts.await_args.args == ("needle", None, 10)
    assert fts.await_args.kwargs["kb_ids"] == [1, 2, 3]
    assert fts.await_args.kwargs["user_id"] == 2


async def test_multi_kb_conversation_blocks_deleting_its_library(client, admin_token, test_db):
    headers = await seed(client, test_db)
    created = await client.post("/api/conversations", headers=headers, json={})
    assert created.status_code == 200, created.text
    response = await client.delete("/api/knowledge-bases/2", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
