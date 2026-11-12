import json
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.main import app
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, Message


@pytest.mark.parametrize("has_settings", [True, False])
async def test_stream_does_not_hold_request_transaction(client, admin_token, test_db, monkeypatch, has_settings):
    from app.database import get_db
    from app.models import SystemSetting
    conv_id = await seed_conversation(test_db, with_chunks=True)
    async with test_db() as db:
        conv = await db.get(Conversation, conv_id)
        conv.title = "已有标题"
        if not has_settings:
            await db.delete(await db.get(SystemSetting, 1))
        await db.commit()
    captured = []
    async def dependency():
        async with test_db() as db:
            captured.append(db)
            yield db
    app.dependency_overrides[get_db] = dependency
    started, release = asyncio.Event(), asyncio.Event()
    class Graph:
        async def astream(self, payload, **kwargs):
            started.set()
            await release.wait()
            yield AIMessageChunk(content="回答"), {}
        async def aget_state(self, config):
            return SimpleNamespace(values={"sources": []})
    monkeypatch.setattr(app.state, "graph", Graph(), raising=False)
    pending = asyncio.create_task(client.post(f"/api/conversations/{conv_id}/chat",
        headers={"Authorization": f"Bearer {admin_token}"}, json={"content": "问题"}))
    try:
        await asyncio.wait_for(started.wait(), 3)
        assert not captured[-1].in_transaction()
    finally:
        release.set()
        response = await asyncio.wait_for(pending, 3)
    assert response.status_code == 200
    async with test_db() as db:
        assert await db.get(SystemSetting, 1) is not None


@pytest.fixture
def chat_graph(monkeypatch):
    class FakeGraph:
        def __init__(self):
            self.inputs = []
            self.sources = []

        async def astream(self, payload, **kwargs):
            self.inputs.append(payload)
            references = "".join(f"[来源{s['index']}]" for s in self.sources)
            yield AIMessageChunk(content="测试回答" + references), {}

        async def aget_state(self, config):
            return SimpleNamespace(values={"sources": self.sources})

    graph = FakeGraph()
    monkeypatch.setattr(app.state, "graph", graph, raising=False)
    monkeypatch.setattr("app.routers.chat.generate_title", AsyncMock(return_value="测试标题"))
    return graph


async def seed_conversation(test_db, kb_id=1, user_id=1, with_chunks=False):
    async with test_db() as db:
        conv = Conversation(user_id=user_id, kb_id=kb_id, title="")
        db.add(conv)
        await db.commit()
        db.add(Message(conversation_id=conv.id, role="assistant", content="已有历史"))
        if with_chunks:
            record = FileRecord(kb_id=kb_id, filename="test.md", file_type="md", uploaded_by=1)
            db.add(record)
            await db.flush()
            db.add(Chunk(file_id=record.id, chunk_index=0, content="测试资料"))
        await db.commit()
        return conv.id


@pytest.mark.parametrize("kb_id", [1, None])
async def test_history_readable_without_usable_kb(client, admin_token, test_db, kb_id):
    conv_id = await seed_conversation(test_db, kb_id=kb_id)
    response = await client.get(f"/api/conversations/{conv_id}/messages",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == (200 if kb_id else 404)
    if kb_id:
        assert response.json()[0]["content"] == "已有历史"


async def test_history_still_rejects_other_users_conversation(client, admin_token, test_db):
    conv_id = await seed_conversation(test_db, user_id=2)
    response = await client.get(f"/api/conversations/{conv_id}/messages",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


@pytest.mark.parametrize("body,status", [({"kb_id": 0}, 400),
                                         ({"kb_id": -1}, 400), ({"kb_id": 999}, 404)])
async def test_create_conversation_rejects_invalid_kb(client, admin_token, test_db, body, status):
    response = await client.post("/api/conversations", json=body,
                                 headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    async with test_db() as db:
        assert await db.scalar(select(Conversation.id)) is None


async def test_create_conversation_accepts_existing_empty_kb(client, admin_token):
    response = await client.post("/api/conversations", json={"kb_id": 1},
                                 headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert response.json()["kb_id"] == 1


@pytest.mark.parametrize("scenario,status", [
    ("unbound", 404), ("missing_kb", 400), ("empty_kb", 400),
    ("switch_kb", 400), ("blank_question", 400), ("invalid_binding", 400),
])
async def test_chat_validation_has_no_side_effects(
    client, admin_token, test_db, chat_graph, scenario, status,
):
    kb_id = None if scenario in {"unbound", "missing_kb", "invalid_binding"} else 1
    conv_id = await seed_conversation(test_db, kb_id=kb_id, with_chunks=scenario == "blank_question")
    body = {"content": "   " if scenario == "blank_question" else "测试问题"}
    if scenario == "missing_kb":
        body["kb_id"] = 999
    elif scenario == "invalid_binding":
        body["kb_id"] = 0
    elif scenario == "switch_kb":
        async with test_db() as db:
            db.add(KnowledgeBase(id=2, name="另一库", created_by=1))
            await db.commit()
        body["kb_id"] = 2
    response = await client.post(f"/api/conversations/{conv_id}/chat", json=body,
                                 headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == status
    assert chat_graph.inputs == []
    async with test_db() as db:
        conv = await db.get(Conversation, conv_id)
        assert conv.title == ""
        assert conv.kb_id == kb_id
        assert (await db.scalars(select(Message.content).where(Message.conversation_id == conv_id))).all() == ["已有历史"]


async def test_valid_bound_chat_streams(
    client, admin_token, test_db, chat_graph,
):
    conv_id = await seed_conversation(test_db, with_chunks=True)
    response = await client.post(
        f"/api/conversations/{conv_id}/chat", json={"content": "测试问题", "kb_id": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert any(event.get("content") == "测试回答" for event in events)
    assert events[-1]["type"] == "done"
    assert chat_graph.inputs[0]["kb_id"] == "1"
    async with test_db() as db:
        assert (await db.get(Conversation, conv_id)).kb_id == 1
        roles = (await db.scalars(select(Message.role).where(Message.conversation_id == conv_id).order_by(Message.id))).all()
        assert roles == ["assistant", "user", "assistant"]


async def test_same_filename_sources_stay_separate_and_persist_ids(
    client, admin_token, test_db, chat_graph,
):
    conv_id = await seed_conversation(test_db, with_chunks=True)
    async with test_db() as db:
        first = await db.scalar(select(Chunk))
        other = FileRecord(kb_id=1, filename="test.md", file_type="md", uploaded_by=1)
        db.add(other)
        await db.flush()
        second = Chunk(file_id=other.id, chunk_index=0, content="另一文件")
        db.add(second)
        await db.commit()
        for index, chunk in enumerate([first, second], 1):
            chat_graph.sources.append({"index": index, "source": "test.md", "chunk_id": str(chunk.id),
                "file_id": str(chunk.file_id), "file_version": 1, "chunk_index": "0", "excerpt": f"摘要{index}"})
    response = await client.post(f"/api/conversations/{conv_id}/chat",
        headers={"Authorization": f"Bearer {admin_token}"}, json={"content": "测试问题", "kb_id": 1})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    groups = next(event["sources"] for event in events if event["type"] == "sources")
    assert len(groups) == 2
    assert groups[0]["file_id"] != groups[1]["file_id"]
    for group in groups:
        excerpt = group["excerpts"][0]
        assert excerpt["chunk_id"] and excerpt["file_version"] == 1
        assert group["file_version"] == 1
    async with test_db() as db:
        message = await db.scalar(
            select(Message).where(Message.conversation_id == conv_id, Message.role == "assistant")
            .order_by(Message.id.desc()).limit(1)
        )
        assert json.loads(message.sources) == groups
