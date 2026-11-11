import pytest
from sqlalchemy import delete

from app.config import settings
from app.models import Chunk, FileRecord


@pytest.fixture
async def chunk_file(test_db):
    async with test_db() as db:
        record = FileRecord(filename="guide.md", file_type="md", kb_id=1, uploaded_by=1)
        other = FileRecord(filename="other.md", file_type="md", kb_id=1, uploaded_by=1)
        db.add_all([record, other])
        await db.flush()
        db.add_all([
            Chunk(id=10, file_id=record.id, chunk_index=0, content="目标分块完整正文", embedding=[0.1] * settings.embed_dim),
            Chunk(id=11, file_id=record.id, chunk_index=1, content="不应返回的另一分块"),
        ])
        await db.commit()
        return record.id, other.id


async def test_get_single_chunk_is_authenticated(client, chunk_file):
    response = await client.get("/api/chunks/10")
    assert response.status_code == 401


@pytest.mark.parametrize("ordinary", [False, True])
async def test_get_only_requested_chunk(client, admin_token, chunk_file, ordinary):
    file_id, _ = chunk_file
    token = admin_token
    if ordinary:
        token = (await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})).json()["token"]
    response = await client.get(f"/api/chunks/10?file_id={file_id}&version=1",
                                headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["id"] == 10 and data["file_id"] == file_id and data["file_version"] == 1
    assert data["content"] == "目标分块完整正文"
    assert data["filename"] == "guide.md"
    assert "embedding" not in data
    assert "另一分块" not in response.text


async def test_chunk_cannot_be_read_as_another_file(client, admin_token, chunk_file):
    _, other_id = chunk_file
    response = await client.get(f"/api/chunks/10?file_id={other_id}&version=1",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


async def test_old_reference_is_gone_after_version_switch(client, admin_token, chunk_file, test_db):
    file_id, _ = chunk_file
    async with test_db() as db:
        record = await db.get(FileRecord, file_id)
        record.version = 2
        await db.execute(delete(Chunk).where(Chunk.file_id == file_id))
        db.add(Chunk(id=20, file_id=file_id, chunk_index=0, content="新的内容不属于旧引用"))
        await db.commit()
    headers = {"Authorization": f"Bearer {admin_token}"}
    for chunk_id in [10, 20]:
        response = await client.get(f"/api/chunks/{chunk_id}?file_id={file_id}&version=1", headers=headers)
        assert response.status_code == 410
        assert "更新" in response.json()["detail"]
        assert "新的内容" not in response.text


async def test_deleted_file_reference_is_missing(client, admin_token, chunk_file, test_db):
    file_id, _ = chunk_file
    async with test_db() as db:
        await db.delete(await db.get(FileRecord, file_id))
        await db.commit()
    response = await client.get(f"/api/chunks/10?file_id={file_id}&version=1",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 404


async def test_old_active_chunks_remain_readable_while_updating(client, admin_token, chunk_file, test_db):
    file_id, _ = chunk_file
    async with test_db() as db:
        (await db.get(FileRecord, file_id)).status = "processing"
        await db.commit()
    response = await client.get(f"/api/chunks/10?file_id={file_id}&version=1",
                                headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert response.json()["content"] == "目标分块完整正文"
