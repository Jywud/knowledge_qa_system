import asyncio
import json
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import func, select

from app.main import app
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, Message, RoleKnowledgeBase


async def seed(test_db, *, ready=True):
    async with test_db() as db:
        conv = Conversation(user_id=2, kb_id=1, title="测试对话", rbac_ready=ready)
        file = FileRecord(kb_id=1, filename="guide.md", file_type="md", uploaded_by=1)
        db.add_all([conv, file])
        await db.flush()
        db.add(Chunk(file_id=file.id, chunk_index=0, content="知识库资料"))
        await db.commit()
        return conv.id


async def employee_headers(client):
    response = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


async def test_old_conversations_are_not_loaded_or_rebound(client, test_db):
    conv_id = await seed(test_db, ready=False)
    headers = await employee_headers(client)
    assert (await client.get("/api/conversations", headers=headers)).json() == []
    assert (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).status_code == 404
    assert (await client.post(f"/api/conversations/{conv_id}/chat", headers=headers,
                              json={"content": "继续", "kb_id": 1})).status_code == 404


@pytest.mark.parametrize("multi_scope", [False, True])
async def test_revoke_stops_silent_model_without_saving_or_reusing_state(client, admin_token, test_db, monkeypatch, multi_scope):
    conv_id = await seed(test_db)
    if multi_scope:
        async with test_db() as db:
            db.add(KnowledgeBase(id=2, name="跨库授权", created_by=1))
            await db.flush()
            db.add(RoleKnowledgeBase(role_id=2, kb_id=2))
            conv = await db.get(Conversation, conv_id)
            conv.kb_id, conv.kb_scope = None, "[1, 2]"
            await db.commit()
    headers = await employee_headers(client)
    started, cancelled = asyncio.Event(), asyncio.Event()
    class SilentGraph:
        async def astream(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
                yield AIMessageChunk(content="不可输出"), {}
            finally:
                cancelled.set()
    monkeypatch.setattr(app.state, "graph", SilentGraph(), raising=False)
    pending = asyncio.create_task(client.post(f"/api/conversations/{conv_id}/chat", headers=headers,
                                               json={"content": "问题"}))
    try:
        await asyncio.wait_for(started.wait(), 3)
        response = await client.put("/api/roles/2", headers={"Authorization": f"Bearer {admin_token}"},
                                    json={"name": "测试角色", "kb_ids": [1] if multi_scope else []})
        assert response.status_code == 200
        result = await asyncio.wait_for(pending, 5)
    finally:
        if not pending.done():
            pending.cancel()
    assert cancelled.is_set()
    assert any(event.get("code") == "permission_revoked" for event in events(result))
    assert events(result)[-1]["type"] == "done"
    async with test_db() as db:
        assert await db.scalar(select(func.count()).select_from(Message).where(
            Message.conversation_id == conv_id, Message.role == "assistant")) == 0
        assert (await db.get(Conversation, conv_id)).memory_thread_id is None
    assert (await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)).status_code == 404


async def test_only_committed_completed_thread_can_supply_next_turn(client, test_db, monkeypatch):
    conv_id = await seed(test_db)
    headers = await employee_headers(client)
    class Graph:
        def __init__(self):
            self.states, self.calls = {}, []
        async def astream(self, payload, config, **kwargs):
            thread = config["configurable"]["thread_id"]
            self.calls.append((thread, payload))
            self.states[thread] = {"messages": payload["messages"] + [AIMessage(content="回答")], "sources": []}
            yield AIMessageChunk(content="回答"), {}
        async def aget_state(self, config):
            return SimpleNamespace(values=self.states[config["configurable"]["thread_id"]])
    graph = Graph()
    monkeypatch.setattr(app.state, "graph", graph, raising=False)
    for question in ["问题一", "问题二"]:
        response = await client.post(f"/api/conversations/{conv_id}/chat", headers=headers, json={"content": question})
        assert events(response)[-1]["type"] == "done"
        assert not any(event["type"] == "error" for event in events(response))
    assert graph.calls[0][0] != graph.calls[1][0]
    assert all(thread.startswith("rbac-v1-user-2-") for thread, _ in graph.calls)
    assert len(graph.calls[1][1]["messages"]) == 3
    assert graph.calls[1][1]["user_id"] == 2


async def test_failed_thread_is_never_reused(client, test_db, monkeypatch):
    conv_id = await seed(test_db)
    headers = await employee_headers(client)
    class BrokenGraph:
        async def astream(self, payload, **kwargs):
            yield AIMessageChunk(content="部分内容"), {}
            raise RuntimeError("模型中断")
    monkeypatch.setattr(app.state, "graph", BrokenGraph(), raising=False)
    response = await client.post(f"/api/conversations/{conv_id}/chat", headers=headers, json={"content": "问题"})
    assert any(event["type"] == "error" for event in events(response))
    async with test_db() as db:
        assert (await db.get(Conversation, conv_id)).memory_thread_id is None


async def test_revoke_discards_completed_generation_waiting_for_slow_client(client, admin_token, test_db, monkeypatch):
    from starlette.requests import Request
    from app.models import User
    from app.routers.chat import chat
    from app.schemas import ChatRequest

    conv_id = await seed(test_db)
    generated = asyncio.Event()

    class Graph:
        async def astream(self, *args, **kwargs):
            for _ in range(20):
                yield AIMessageChunk(content="待发送内容"), {}
        async def aget_state(self, config):
            generated.set()
            return SimpleNamespace(values={"sources": []})

    monkeypatch.setattr(app.state, "graph", Graph(), raising=False)
    async with test_db() as db:
        response = await chat(conv_id, ChatRequest(content="问题"),
                              Request({"type": "http", "app": app}), await db.get(User, 2), db)
    iterator = response.body_iterator
    await anext(iterator)  # 暂停客户端消费，允许模型先完成并把内容放进队列。
    await asyncio.wait_for(generated.wait(), 3)
    async with test_db() as db:
        for _ in range(30):
            await db.rollback()
            if (await db.get(Conversation, conv_id)).memory_thread_id:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("模型应先完成提交")
    result = await client.put("/api/roles/2", headers={"Authorization": f"Bearer {admin_token}"},
                              json={"name": "测试角色", "kb_ids": []})
    assert result.status_code == 200
    await asyncio.sleep(1.2)
    remaining = [json.loads(item[6:]) async for item in iterator]
    assert [item["type"] for item in remaining] == ["error", "done"]
    assert remaining[0]["code"] == "permission_revoked"
