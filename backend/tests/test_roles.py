import pytest


async def test_role_list_requires_system_admin(client, admin_token):
    response = await client.get("/api/roles", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    assert any(role["system_key"] == "system_admin" for role in response.json())


async def test_create_user_requires_role_selection(client, admin_token):
    response = await client.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"},
                                 json={"username": "unassigned", "password": "valid123"})
    assert response.status_code == 422


async def test_role_assigns_knowledge_bases(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.post("/api/roles", headers=headers,
                                 json={"name": "销售", "description": "", "kb_ids": [1]})
    assert response.status_code == 200
    role = response.json()
    created = await client.post("/api/users", headers=headers,
                                json={"username": "sales", "password": "valid123", "role_ids": [role["id"]]})
    assert created.status_code == 200
    assert created.json()["roles"][0]["name"] == "销售"
