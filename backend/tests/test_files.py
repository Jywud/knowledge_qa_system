import io
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_upload_md_file(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    content = "# 测试文档\n\n这是测试内容，用于验证上传流程。".encode("utf-8")
    files = {"file": ("test.md", io.BytesIO(content), "text/markdown")}
    data = {"kb_id": "1"}
    with (
        patch("app.services.document_service.ingest_file", new_callable=AsyncMock) as mock,
        patch("app.routers.files.process_file_record", new_callable=AsyncMock),
    ):
        mock.return_value = 1
        resp = await client.post("/api/files", headers=headers, files=files, data=data)
    assert resp.status_code == 200
    assert resp.json()["filename"] == "test.md"
    assert resp.json()["status"] == "processing"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_type(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    files = {"file": ("test.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    data = {"kb_id": "1"}
    resp = await client.post("/api/files", headers=headers, files=files, data=data)
    assert resp.status_code == 400
