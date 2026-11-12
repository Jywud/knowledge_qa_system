"""通过 HTTP 与隔离数据库验证角色管理的授权、原子性和数据边界。"""
import hashlib

import pytest
from sqlalchemy import func, select, text

from app.models import Conversation, FileRecord, Role, RoleKnowledgeBase, User, UserRole


def headers(token):
    return {'Authorization': f'Bearer {token}'}


async def login(client, username='alice', password='pass1'):
    response = await client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_role_crud_deduplicates_knowledge_base_grants(client, admin_token, test_db):
    auth = headers(admin_token)
    response = await client.post('/api/roles', headers=auth,
                                json={'name': '  销售  ', 'description': '销售资料', 'kb_ids': [1, 1]})
    assert response.status_code == 200, response.text
    created = response.json()
    assert created['name'] == '销售'
    assert created['kb_ids'] == [1]
    role_id = created['id']
    response = await client.put(f'/api/roles/{role_id}', headers=auth,
                               json={'name': '销售新版', 'description': '调整', 'kb_ids': [1, 1, 1]})
    assert response.status_code == 200, response.text
    assert response.json()['kb_ids'] == [1]
    async with test_db() as db:
        assert await db.scalar(select(func.count()).select_from(RoleKnowledgeBase)
                               .where(RoleKnowledgeBase.role_id == role_id)) == 1
    assert (await client.delete(f'/api/roles/{role_id}', headers=auth)).status_code == 200
    async with test_db() as db:
        assert await db.get(Role, role_id) is None
        assert await db.scalar(select(func.count()).select_from(RoleKnowledgeBase)
                               .where(RoleKnowledgeBase.role_id == role_id)) == 0


async def test_unknown_knowledge_base_rejects_create_and_update_atomically(client, admin_token, test_db):
    auth = headers(admin_token)
    async with test_db() as db:
        db.add(Conversation(id=10, user_id=2, kb_id=1, memory_epoch=4))
        await db.commit()
    create = await client.post('/api/roles', headers=auth,
                               json={'name': '不应创建', 'kb_ids': [1, 999999]})
    assert create.status_code == 400, create.text
    update = await client.put('/api/roles/2', headers=auth,
                               json={'name': '不应改名', 'kb_ids': [999999]})
    assert update.status_code == 400, update.text
    async with test_db() as db:
        assert await db.scalar(select(Role.id).where(Role.name == '不应创建')) is None
        assert (await db.get(Role, 2)).name == '测试角色'
        assert (await db.scalars(select(RoleKnowledgeBase.kb_id)
                                 .where(RoleKnowledgeBase.role_id == 2))).all() == [1]
        assert (await db.get(Conversation, 10)).memory_epoch == 4


async def test_assigned_role_cannot_be_deleted(client, admin_token, test_db):
    response = await client.delete('/api/roles/2', headers=headers(admin_token))
    assert response.status_code == 409, response.text
    async with test_db() as db:
        assert await db.get(Role, 2) is not None
        assert await db.get(UserRole, (2, 2)) is not None
        assert await db.get(RoleKnowledgeBase, (2, 1)) is not None


async def test_builtin_role_cannot_be_changed_deleted_or_created_by_client(client, admin_token, test_db):
    auth = headers(admin_token)
    changed = await client.put('/api/roles/1', headers=auth,
                              json={'name': '被修改', 'kb_ids': []})
    assert changed.status_code == 400, changed.text
    assert (await client.delete('/api/roles/1', headers=auth)).status_code == 409
    forged = await client.post('/api/roles', headers=auth,
                              json={'name': '伪管理员', 'system_key': 'system_admin'})
    assert forged.status_code == 422, forged.text
    async with test_db() as db:
        builtin = await db.get(Role, 1)
        assert (builtin.name, builtin.system_key) == ('系统管理员', 'system_admin')


@pytest.mark.parametrize('name, status', [(' \t\n ', 400), ('测试角色', 409), (' 测试角色 ', 409)])
async def test_invalid_role_names_leave_no_partial_grants(client, admin_token, test_db, name, status):
    response = await client.post('/api/roles', headers=headers(admin_token),
                                 json={'name': name, 'kb_ids': [1]})
    assert response.status_code == status, response.text
    async with test_db() as db:
        assert await db.scalar(select(func.count()).select_from(Role)) == 2
        assert await db.scalar(select(func.count()).select_from(RoleKnowledgeBase)) == 1


async def test_unknown_roles_do_not_create_account_or_change_existing_assignment(client, admin_token, test_db):
    auth = headers(admin_token)
    created = await client.post('/api/users', headers=auth,
                               json={'username': 'no_partial_user', 'password': 'valid123', 'role_ids': [2, 999999]})
    assert created.status_code == 400, created.text
    assigned = await client.put('/api/users/2/roles', headers=auth, json={'role_ids': [1, 999999]})
    assert assigned.status_code == 400, assigned.text
    async with test_db() as db:
        assert await db.scalar(select(User.id).where(User.username == 'no_partial_user')) is None
        assert (await db.scalars(select(UserRole.role_id).where(UserRole.user_id == 2))).all() == [2]


async def test_last_admin_cannot_remove_own_admin_role(client, admin_token, test_db):
    response = await client.put('/api/users/1/roles', headers=headers(admin_token), json={'role_ids': [2]})
    assert response.status_code == 409, response.text
    assert (await client.get('/api/roles', headers=headers(admin_token))).status_code == 200
    async with test_db() as db:
        assert (await db.scalars(select(UserRole.role_id).where(UserRole.user_id == 1))).all() == [1]


async def test_second_admin_allows_demotion_and_existing_token_loses_privileges(client, admin_token, test_db):
    auth = headers(admin_token)
    created = await client.post('/api/users', headers=auth,
                               json={'username': 'second_admin', 'password': 'valid123', 'role_ids': [1, 1]})
    assert created.status_code == 200, created.text
    assert [role['id'] for role in created.json()['roles']] == [1]
    second = await login(client, 'second_admin', 'valid123')
    response = await client.put('/api/users/1/roles', headers=auth, json={'role_ids': [2, 2]})
    assert response.status_code == 200, response.text
    assert response.json()['is_admin'] is False
    assert [role['id'] for role in response.json()['roles']] == [2]
    assert (await client.get('/api/roles', headers=auth)).status_code == 403
    assert (await client.post('/api/roles', headers=auth, json={'name': '越权角色'})).status_code == 403
    assert (await client.get('/api/roles', headers=headers(second['token']))).status_code == 200
    me = await client.get('/api/auth/me', headers=auth)
    assert me.status_code == 200
    assert me.json()['is_admin'] is False


async def test_employee_cannot_manage_roles_or_self_promote(client, test_db):
    auth = headers((await login(client))['token'])
    for method, url, body in (
        ('get', '/api/roles', None),
        ('post', '/api/roles', {'name': '越权'}),
        ('put', '/api/roles/2', {'name': '越权', 'kb_ids': []}),
        ('delete', '/api/roles/2', None),
        ('put', '/api/users/2/roles', {'role_ids': [1]}),
    ):
        response = await client.request(method, url, headers=auth, **({'json': body} if body else {}))
        assert response.status_code == 403, (url, response.text)
    async with test_db() as db:
        assert (await db.scalars(select(UserRole.role_id).where(UserRole.user_id == 2))).all() == [2]


async def test_login_and_me_expose_only_public_role_shape(client):
    for username, password, expected_admin in [('admin', '123456', True), ('alice', 'pass1', False)]:
        result = await login(client, username, password)
        assert set(result) == {'token', 'user'}
        assert set(result['user']) == {'id', 'username', 'roles', 'is_admin'}
        assert result['user']['is_admin'] is expected_admin
        assert all(set(role) == {'id', 'name', 'system_key'} for role in result['user']['roles'])
        for path in ('/api/auth/me', '/api/users/me'):
            response = await client.get(path, headers=headers(result['token']))
            assert response.status_code == 200, response.text
            assert response.json() == result['user']


async def knowledge_fingerprint(db):
    rows = [(table, (await db.execute(text(f'SELECT * FROM {table} ORDER BY id'))).all())
            for table in ('knowledge_bases', 'files', 'chunks')]
    return hashlib.sha256(repr(rows).encode()).hexdigest()


async def test_role_grant_changes_only_affected_memory_epochs_and_preserves_documents(client, admin_token, test_db, tmp_path):
    original_bytes = b'unchanged original file\x00bytes'
    original_path = tmp_path / 'preserved.txt'
    original_path.write_bytes(original_bytes)
    async with test_db() as db:
        db.add(FileRecord(id=20, kb_id=1, filename='preserved.txt', file_type='txt', uploaded_by=1, size=len(original_bytes)))
        db.add_all([Conversation(id=10, user_id=1, kb_id=1, memory_epoch=3),
                    Conversation(id=11, user_id=2, kb_id=1, memory_epoch=8)])
        await db.flush()
        await db.execute(text("INSERT INTO chunks (id,file_id,chunk_index,page_no,content) VALUES (20,20,0,1,'原始分块正文')"))
        await db.commit()
        before = await knowledge_fingerprint(db)
    response = await client.put('/api/roles/2', headers=headers(admin_token),
                                json={'name': '测试角色', 'description': '', 'kb_ids': []})
    assert response.status_code == 200, response.text
    async with test_db() as db:
        assert (await db.get(Conversation, 10)).memory_epoch == 3
        assert (await db.get(Conversation, 11)).memory_epoch == 9
        assert await knowledge_fingerprint(db) == before
        assert await db.get(RoleKnowledgeBase, (2, 1)) is None
    assert original_path.read_bytes() == original_bytes
    employee = headers((await login(client))['token'])
    response = await client.get('/api/knowledge-bases', headers=employee)
    assert response.status_code == 200, response.text
    assert response.json() == []
