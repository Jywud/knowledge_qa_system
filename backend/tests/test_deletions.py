import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Chunk, Conversation, FileRecord, KnowledgeBase, Message, User


async def test_delete_kb_with_conversation_returns_conflict(client, admin_token, test_db):
    async with test_db() as db:
        conv = Conversation(user_id=2, kb_id=1, title="keep history")
        db.add(conv)
        await db.commit()
        db.add(Message(conversation_id=conv.id, role="user", content="keep message"))
        await db.commit()
    response = await client.delete("/api/knowledge-bases/1", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
    assert "会话" in response.json()["detail"]
    async with test_db() as db:
        assert await db.get(KnowledgeBase, 1) is not None
        assert (await db.scalars(select(Message.content))).all() == ["keep message"]


async def test_delete_kb_with_processing_file_returns_conflict(client, admin_token, test_db):
    async with test_db() as db:
        db.add(FileRecord(kb_id=1, filename="busy.md", file_type="md", status="processing", uploaded_by=1))
        await db.commit()
    response = await client.delete("/api/knowledge-bases/1", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
    async with test_db() as db:
        assert await db.get(KnowledgeBase, 1) is not None
        assert await db.scalar(select(FileRecord.id)) is not None


@pytest.mark.parametrize("reference", ["knowledge_base", "file", "conversation", "audit"])
async def test_delete_referenced_user_returns_conflict(client, admin_token, test_db, reference):
    objects = {
        "knowledge_base": KnowledgeBase(name="owned", created_by=2),
        "file": FileRecord(kb_id=1, filename="owned.md", file_type="md", uploaded_by=2),
        "conversation": Conversation(user_id=2, kb_id=1),
        "audit": AuditLog(operator_id=2, operator_name="alice", action="user.change_password"),
    }
    async with test_db() as db:
        db.add(objects[reference])
        await db.commit()
    response = await client.delete("/api/users/2", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
    assert response.json()["detail"]
    async with test_db() as db:
        assert await db.get(User, 2) is not None
        obj = objects[reference]
        assert await db.get(type(obj), obj.id) is not None


async def test_delete_unreferenced_user_succeeds(client, admin_token, test_db):
    response = await client.delete("/api/users/2", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    async with test_db() as db:
        assert await db.get(User, 2) is None
        assert await db.scalar(select(AuditLog.action)) == "user.delete"


async def test_delete_kb_without_conversations_succeeds(client, admin_token, test_db, tmp_path):
    async with test_db() as db:
        record = FileRecord(kb_id=1, filename="remove.md", file_type="md", uploaded_by=1)
        db.add(record)
        await db.commit()
        db.add(Chunk(file_id=record.id, chunk_index=0, content="remove"))
        await db.commit()
        disk_file = tmp_path / f"{record.id}_remove.md"
        disk_file.write_bytes(b"remove")
        version_dir = tmp_path / ".versions"
        version_dir.mkdir()
        version_file = version_dir / f"{record.id}_v2_remove.md"
        version_file.write_bytes(b"remove")
    response = await client.delete("/api/knowledge-bases/1", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert not disk_file.exists()
    assert not version_file.exists()
    async with test_db() as db:
        assert await db.get(KnowledgeBase, 1) is None
        assert await db.scalar(select(FileRecord.id)) is None
        assert await db.scalar(select(Chunk.id)) is None
        assert await db.scalar(select(AuditLog.action)) == "kb.delete"


@pytest.mark.parametrize("url", ["/api/knowledge-bases/1", "/api/users/2"])
async def test_delete_requires_admin(client, url):
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    response = await client.delete(url, headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert response.status_code == 403


@pytest.mark.parametrize("url", ["/api/knowledge-bases/999", "/api/users/999"])
async def test_delete_missing_returns_404(client, admin_token, url):
    response = await client.delete(url, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


async def test_delete_self_remains_forbidden(client, admin_token):
    response = await client.delete("/api/users/1", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 400


@pytest.mark.parametrize("model,url", [(User, "/api/users/2"), (KnowledgeBase, "/api/knowledge-bases/1")])
async def test_delete_commit_conflict_rolls_back(client, admin_token, test_db, monkeypatch, model, url):
    original_commit = AsyncSession.commit

    async def conflicting_commit(db):
        if any(isinstance(obj, model) for obj in db.deleted):
            raise IntegrityError("DELETE", {}, RuntimeError("concurrent foreign key reference"))
        await original_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", conflicting_commit)
    response = await client.delete(url, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 409
    async with test_db() as db:
        assert await db.get(model, int(url.rsplit("/", 1)[1])) is not None
        assert await db.scalar(select(AuditLog.id)) is None
