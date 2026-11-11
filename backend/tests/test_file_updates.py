from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Chunk, FileRecord
from app.services.document_service import reindex_missing_embeddings


async def test_reindex_failure_rolls_back_one_file_and_continues(test_db, existing_file, embeddings):
    async with test_db() as db:
        second = FileRecord(kb_id=1, filename="second.md", file_type="md", uploaded_by=1)
        db.add(second)
        await db.flush()
        second_id = second.id
        db.add(Chunk(file_id=second_id, chunk_index=0, content="old second"))
        await db.commit()
    (existing_file.path.parent / f"{second_id}_second.md").write_text("second document", encoding="utf8")
    async def embed(texts):
        if "original" in texts:
            raise RuntimeError("embedding unavailable")
        return [[0.1] * settings.embed_dim for _ in texts]
    embeddings.aembed_documents.side_effect = embed
    async with test_db() as db:
        assert await reindex_missing_embeddings(db) == 1
    async with test_db() as db:
        rows = (await db.scalars(select(Chunk).order_by(Chunk.file_id))).all()
        assert [(row.file_id, row.content) for row in rows] == [(existing_file.id, "original content"), (second_id, "second document")]
        assert rows[0].embedding is None
        assert rows[1].embedding is not None


@pytest.fixture
async def existing_file(test_db, tmp_path):
    async with test_db() as db:
        record = FileRecord(
            kb_id=1, filename="same.md", file_type="md", size=8,
            version=1, status="ready", uploaded_by=1,
        )
        db.add(record)
        await db.commit()
        db.add(Chunk(file_id=record.id, chunk_index=0, content="original content"))
        await db.commit()
        path = tmp_path / f"{record.id}_same.md"
        path.write_bytes(b"original")
        return SimpleNamespace(id=record.id, path=path)


@pytest.fixture
def embeddings(monkeypatch):
    async def embed(texts):
        return [[0.1] * settings.embed_dim for _ in texts]

    provider = SimpleNamespace(aembed_documents=AsyncMock(side_effect=embed))
    monkeypatch.setattr("app.services.document_service.get_embeddings", lambda: provider)
    return provider


async def assert_original_preserved(test_db, existing_file):
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        contents = (await db.scalars(select(Chunk.content).where(
            Chunk.file_id == existing_file.id
        ))).all()
        assert contents == ["original content"]
        assert (record.filename, record.size, record.version) == ("same.md", 8, 1)
        assert record.status == "ready"
    assert existing_file.path.read_bytes() == b"original"
    assert not list(existing_file.path.parent.glob(".pending/*"))


async def test_oversize_same_name_update_preserves_original(
    client, admin_token, test_db, existing_file, monkeypatch,
):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    response = await client.put(
        f"/api/files/{existing_file.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("same.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 413
    await assert_original_preserved(test_db, existing_file)


@pytest.mark.parametrize("failure", ["embedding", "parse", "empty", "rename", "commit", "vector_count"])
async def test_failed_update_preserves_original(
    client, admin_token, test_db, existing_file, embeddings, monkeypatch, failure,
):
    if failure == "embedding":
        embeddings.aembed_documents.side_effect = RuntimeError("embedding unavailable")
    elif failure == "vector_count":
        embeddings.aembed_documents.side_effect = None
        embeddings.aembed_documents.return_value = []
    elif failure == "parse":
        def fail_load(*args):
            raise ValueError("invalid document")
        monkeypatch.setattr("app.services.document_service._load_documents", fail_load)
    elif failure == "rename":
        def fail_replace(*args):
            raise OSError("disk unavailable")
        monkeypatch.setattr(Path, "replace", fail_replace)
    elif failure == "commit":
        original_commit = AsyncSession.commit

        async def fail_version_commit(db):
            if any(isinstance(obj, FileRecord) and obj.version == 2 and obj.status == "ready"
                   for obj in db.identity_map.values()):
                raise RuntimeError("commit failed")
            await original_commit(db)
        monkeypatch.setattr(AsyncSession, "commit", fail_version_commit)

    response = await client.put(
        f"/api/files/{existing_file.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("same.md", b"" if failure == "empty" else b"replacement", "text/markdown")},
    )
    assert response.status_code == 200
    await assert_original_preserved(test_db, existing_file)
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert "更新失败" in record.status_message
    assert list(existing_file.path.parent.glob(f"{existing_file.id}_*")) == [existing_file.path]
    assert not list(existing_file.path.parent.glob(".versions/*"))


async def test_update_keeps_old_version_until_background_success(
    client, admin_token, test_db, existing_file, embeddings, monkeypatch,
):
    scheduled = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **kw: scheduled.append((fn, a, kw)))
    response = await client.put(
        f"/api/files/{existing_file.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("new.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert response.json()["filename"] == "same.md"
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert record.status == "processing"
        assert (await db.scalars(select(Chunk.content))).all() == ["original content"]
    assert existing_file.path.read_bytes() == b"original"

    fn, args, kwargs = scheduled.pop()
    await fn(*args, **kwargs)
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert (record.filename, record.version, record.size, record.status) == ("new.md", 2, 11, "ready")
        assert (await db.scalars(select(Chunk.content))).all() == ["replacement"]
    assert not existing_file.path.exists()
    assert (existing_file.path.parent / ".versions" / f"{existing_file.id}_v2_new.md").read_bytes() == b"replacement"
    assert not list(existing_file.path.parent.glob(".pending/*"))


async def test_update_request_commit_failure_cleans_staging(
    client, admin_token, test_db, existing_file, monkeypatch,
):
    original_commit = AsyncSession.commit

    async def fail_processing_commit(db):
        if any(isinstance(obj, FileRecord) and obj.status == "processing"
               for obj in db.identity_map.values()):
            raise RuntimeError("request commit failed")
        await original_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_processing_commit)
    response = await client.put(
        f"/api/files/{existing_file.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("same.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 500
    await assert_original_preserved(test_db, existing_file)


async def test_update_request_lost_commit_acknowledgement_restores_old_status(
    client, admin_token, test_db, existing_file, monkeypatch,
):
    original_commit = AsyncSession.commit

    async def commit_processing_then_fail(db):
        is_request = any(isinstance(obj, FileRecord) and obj.status == "processing"
                         for obj in db.identity_map.values())
        await original_commit(db)
        if is_request:
            raise RuntimeError("request commit acknowledgement lost")
    monkeypatch.setattr(AsyncSession, "commit", commit_processing_then_fail)
    response = await client.put(
        f"/api/files/{existing_file.id}", headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("same.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 500
    await assert_original_preserved(test_db, existing_file)


async def test_request_recovery_does_not_overwrite_another_processing_request(
    client, admin_token, test_db, existing_file, monkeypatch,
):
    original_commit = AsyncSession.commit
    other_timestamp = None

    async def commit_then_simulate_other_request(db):
        nonlocal other_timestamp
        is_request = any(isinstance(obj, FileRecord) and obj.status == "processing"
                         for obj in db.identity_map.values())
        await original_commit(db)
        if is_request:
            async with test_db() as other_db:
                record = await other_db.get(FileRecord, existing_file.id)
                other_timestamp = record.updated_at + timedelta(seconds=1)
                record.updated_at = other_timestamp
                record.status_message = "other request marker"
                await original_commit(other_db)
            raise RuntimeError("request commit acknowledgement lost")
    monkeypatch.setattr(AsyncSession, "commit", commit_then_simulate_other_request)
    response = await client.put(
        f"/api/files/{existing_file.id}", headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("same.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 500
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert (record.status, record.status_message, record.updated_at) == (
            "processing", "other request marker", other_timestamp,
        )
    assert existing_file.path.read_bytes() == b"original"


async def test_reindex_uses_current_version_file(test_db, existing_file, embeddings):
    versions = existing_file.path.parent / ".versions"
    versions.mkdir()
    current_path = versions / f"{existing_file.id}_v2_current.md"
    current_path.write_bytes(b"current version")
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        record.version = 2
        record.filename = "current.md"
        await db.commit()
        assert await reindex_missing_embeddings(db) == 1
        assert (await db.scalars(select(Chunk.content))).all() == ["current version"]


async def test_commit_acknowledgement_failure_keeps_committed_new_file(
    client, admin_token, test_db, existing_file, embeddings, monkeypatch,
):
    original_commit = AsyncSession.commit

    async def commit_then_fail(db):
        is_replacement = any(isinstance(obj, FileRecord) and obj.version == 2 and obj.status == "ready"
                             for obj in db.identity_map.values())
        await original_commit(db)
        if is_replacement:
            raise RuntimeError("connection lost after commit")
    monkeypatch.setattr(AsyncSession, "commit", commit_then_fail)
    response = await client.put(
        f"/api/files/{existing_file.id}", headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("new.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 200
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert (record.version, record.status) == (2, "ready")
        assert (await db.scalars(select(Chunk.content))).all() == ["replacement"]
    current_path = existing_file.path.parent / ".versions" / f"{existing_file.id}_v2_new.md"
    assert current_path.read_bytes() == b"replacement"


async def test_legacy_filename_cannot_collide_with_new_version(
    client, admin_token, test_db, existing_file, embeddings, monkeypatch,
):
    legacy_path = existing_file.path.with_name(f"{existing_file.id}_v2_notes.md")
    existing_file.path.rename(legacy_path)
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        record.filename = "v2_notes.md"
        await db.commit()
    embeddings.aembed_documents.side_effect = RuntimeError("embedding unavailable")
    response = await client.put(
        f"/api/files/{existing_file.id}", headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("notes.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 200
    assert legacy_path.read_bytes() == b"original"
    async with test_db() as db:
        record = await db.get(FileRecord, existing_file.id)
        assert (record.filename, record.version, record.status) == ("v2_notes.md", 1, "ready")


async def test_unknown_commit_outcome_preserves_both_files(
    client, admin_token, test_db, existing_file, embeddings, monkeypatch,
):
    calls = 0

    def failing_recovery_factory():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("database unavailable during recovery")
        return test_db()

    original_commit = AsyncSession.commit

    async def fail_version_commit(db):
        if any(isinstance(obj, FileRecord) and obj.version == 2 and obj.status == "ready"
               for obj in db.identity_map.values()):
            raise RuntimeError("commit outcome unknown")
        await original_commit(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_version_commit)
    monkeypatch.setattr("app.database.SessionLocal", failing_recovery_factory)
    response = await client.put(
        f"/api/files/{existing_file.id}", headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("new.md", b"replacement", "text/markdown")},
    )
    assert response.status_code == 200
    assert existing_file.path.read_bytes() == b"original"
    candidate = existing_file.path.parent / ".versions" / f"{existing_file.id}_v2_new.md"
    assert candidate.read_bytes() == b"replacement"
    async with test_db() as db:
        assert (await db.get(FileRecord, existing_file.id)).version == 1
        assert (await db.scalars(select(Chunk.content))).all() == ["original content"]


async def test_delete_updated_file_cleans_versions_but_keeps_other_files(
    client, admin_token, test_db, existing_file, embeddings,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.put(f"/api/files/{existing_file.id}", headers=headers,
                                files={"file": ("new.md", b"replacement", "text/markdown")})
    assert response.status_code == 200
    versions = existing_file.path.parent / ".versions"
    unrelated = versions / "999_v2_other.md"
    unrelated.write_bytes(b"unrelated")
    response = await client.delete(f"/api/files/{existing_file.id}", headers=headers)
    assert response.status_code == 200
    assert list(versions.iterdir()) == [unrelated]
    assert unrelated.read_bytes() == b"unrelated"
    async with test_db() as db:
        assert await db.get(FileRecord, existing_file.id) is None
        assert await db.scalar(select(Chunk.id)) is None
