import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.main import app
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, Message


@pytest.fixture
def chat_graph(monkeypatch):
    class FakeGraph:
        def __init__(self):
            self.inputs = []

        async def astream(self, payload, **kwargs):
            self.inputs.append(payload)
            yield AIMessageChunk(content="测试回答"), {}

        async def aget_state(self, config):
            return SimpleNamespace(values={"sources": []})

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
    assert response.status_code == 200
    assert response.json()[0]["content"] == "已有历史"


async def test_history_still_rejects_other_users_conversation(client, admin_token, test_db):
    conv_id = await seed_conversation(test_db, user_id=2)
    response = await client.get(f"/api/conversations/{conv_id}/messages",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


@pytest.mark.parametrize("body,status", [({}, 400), ({"kb_id": None}, 400), ({"kb_id": 0}, 400),
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
    ("unbound", 400), ("missing_kb", 404), ("empty_kb", 400),
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


@pytest.mark.parametrize("legacy", [False, True])
async def test_valid_chat_streams_and_binds_legacy_conversation_once(
    client, admin_token, test_db, chat_graph, legacy,
):
    conv_id = await seed_conversation(test_db, with_chunks=True)
    if legacy:
        async with test_db() as db:
            conv = await db.get(Conversation, conv_id)
            conv.kb_id = None
            await db.commit()
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
