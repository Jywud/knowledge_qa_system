import asyncio
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models import Chunk, FileRecord


async def test_retry_reuses_upload_and_accepts_only_one_request(client, admin_token, monkeypatch):
    fail_embedding = True

    async def embed(texts):
        if fail_embedding:
            raise RuntimeError("embedding unavailable")
        return [[0.1] * settings.embed_dim for _ in texts]

    monkeypatch.setattr(
        "app.services.document_service.get_embeddings",
        lambda: SimpleNamespace(aembed_documents=embed),
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    upload = await client.post(
        "/api/files",
        headers=headers,
        data={"kb_id": 1},
        files={"file": ("retry.md", b"The internal project code is ALPHA-52.", "text/markdown")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["id"]

    listing = await client.get("/api/files", headers=headers)
    assert listing.json()[0]["status"] == "failed"
    assert listing.json()[0]["retryable"] is True

    fail_embedding = False
    retry_url = f"/api/files/{file_id}/retry"
    responses = await asyncio.gather(*(client.post(retry_url, headers=headers) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(response.json() for response in responses if response.status_code == 200)
    assert accepted["status"] == "processing"
    assert accepted["status_message"] == ""
    assert accepted["retryable"] is False

    listing = await client.get("/api/files", headers=headers)
    assert [(row["id"], row["status"], row["version"], row["chunk_count"]) for row in listing.json()] == [
        (file_id, "ready", 1, 1)
    ]
    chunks = await client.get(f"/api/files/{file_id}/chunks", headers=headers)
    assert [chunk["content"] for chunk in chunks.json()] == ["The internal project code is ALPHA-52."]
    source = await client.get(
        f"/api/chunks/{chunks.json()[0]['id']}",
        headers=headers,
        params={"file_id": file_id, "version": 1},
    )
    assert source.status_code == 200
    assert source.json()["filename"] == "retry.md"


@pytest.mark.parametrize(
    ("status", "version", "has_chunks", "has_original", "detail"),
    [
        ("failed", 1, False, False, "原文件不存在"),
        ("failed", 1, True, True, "仅支持重试首次入库失败的文件"),
        ("failed", 2, False, True, "仅支持重试首次入库失败的文件"),
        ("ready", 1, False, True, "仅支持重试首次入库失败的文件"),
        ("processing", 1, False, True, "文件正在后台处理中"),
    ],
)
async def test_retry_rejects_ineligible_files(
    client, admin_token, test_db, tmp_path, status, version, has_chunks, has_original, detail,
):
    async with test_db() as db:
        record = FileRecord(
            kb_id=1, filename="retry.md", file_type="md", status=status,
            version=version, uploaded_by=1,
        )
        db.add(record)
        await db.flush()
        if has_chunks:
            db.add(Chunk(file_id=record.id, chunk_index=0, content="Existing content"))
        await db.commit()
    if has_original:
        (tmp_path / f"{record.id}_retry.md").write_text("Original content", encoding="utf-8")

    response = await client.post(
        f"/api/files/{record.id}/retry", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 409
    assert detail in response.json()["detail"]
    async with test_db() as db:
        current = await db.get(FileRecord, record.id)
        assert current.status == status
        assert current.version == version


async def test_retry_requires_admin_even_for_readable_kb(client, test_db):
    async with test_db() as db:
        record = FileRecord(kb_id=1, filename="retry.md", file_type="md", status="failed", uploaded_by=1)
        db.add(record)
        await db.commit()

    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    token = login.json()["token"]
    response = await client.post(
        f"/api/files/{record.id}/retry", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
