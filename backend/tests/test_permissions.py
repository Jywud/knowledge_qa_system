from sqlalchemy import select

from app.models import Chunk, FileRecord, KnowledgeBase, Role, RoleKnowledgeBase, UserRole


async def test_business_user_only_sees_granted_kbs_and_files(client, test_db):
    async with test_db() as db:
        hidden = KnowledgeBase(name="不可见库", created_by=1)
        db.add(hidden)
        await db.flush()
        file = FileRecord(kb_id=hidden.id, filename="secret.md", file_type="md", uploaded_by=1)
        db.add(file)
        await db.flush()
        chunk = Chunk(file_id=file.id, chunk_index=0, content="不可见原文")
        db.add(chunk)
        await db.commit()
        hidden_id, file_id, chunk_id = hidden.id, file.id, chunk.id
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    kbs = await client.get("/api/knowledge-bases", headers=headers)
    assert [kb["id"] for kb in kbs.json()] == [1]
    assert (await client.get("/api/files", headers=headers)).json() == []
    for url in [f"/api/files/{file_id}/chunks", f"/api/chunks/{chunk_id}",
                f"/api/chunks/99999?file_id={file_id}&version=99"]:
        assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.post("/api/conversations", headers=headers, json={"kb_id": hidden_id})).status_code == 404


async def test_roles_union_and_revocation(client, admin_token, test_db):
    async with test_db() as db:
        hidden = KnowledgeBase(name="第二库", created_by=1)
        role = Role(name="第二角色")
        db.add_all([hidden, role])
        await db.flush()
        role_id = role.id
        db.add_all([UserRole(user_id=2, role_id=role.id), RoleKnowledgeBase(role_id=role.id, kb_id=hidden.id)])
        await db.commit()
    login = await client.post("/api/auth/login", json={"username": "alice", "password": "pass1"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert len((await client.get("/api/knowledge-bases", headers=headers)).json()) == 2
    update = await client.put(f"/api/roles/{role_id}", headers={"Authorization": f"Bearer {admin_token}"},
                              json={"name": "第二角色", "kb_ids": []})
    assert update.status_code == 200
    assert [kb["id"] for kb in (await client.get("/api/knowledge-bases", headers=headers)).json()] == [1]


async def test_legacy_role_field_cannot_grant_admin(client, admin_token):
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": "ordinary", "password": "valid123", "role_ids": [2], "role": "admin"})
    assert response.status_code == 422
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": "ordinary", "password": "valid123", "role_ids": [2]})
    assert response.status_code == 200 and response.json()["is_admin"] is False
    login = await client.post("/api/auth/login", json={"username": "ordinary", "password": "valid123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert (await client.get("/api/roles", headers=headers)).status_code == 403
