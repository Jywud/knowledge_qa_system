from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import require_admin
from app.database import get_db
from app.models import KnowledgeBase, Role, RoleKnowledgeBase, User, UserRole
from app.schemas import RoleOut, RoleWrite
from app.services.permission_service import authorization_lock, bump_user_contexts, is_system_admin

router = APIRouter(prefix="/api/roles", tags=["roles"])


async def lock_admin_write(db: AsyncSession, actor_id: int) -> Role:
    guardian = await authorization_lock(db, write=True)
    if not await is_system_admin(db, actor_id):
        raise HTTPException(403, "仅系统管理员可执行该操作")
    return guardian


async def role_out(db: AsyncSession, role: Role) -> dict:
    kb_ids = (await db.scalars(select(RoleKnowledgeBase.kb_id).where(
        RoleKnowledgeBase.role_id == role.id).order_by(RoleKnowledgeBase.kb_id))).all()
    count = await db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))
    return {"id": role.id, "name": role.name, "description": role.description,
            "system_key": role.system_key, "kb_ids": kb_ids, "user_count": count}


async def validate_kb_ids(db: AsyncSession, values: list[int]) -> list[int]:
    ids = sorted(set(values))
    if ids:
        found = (await db.scalars(select(KnowledgeBase.id).where(KnowledgeBase.id.in_(ids))
                                 .with_for_update(read=True))).all()
        if set(found) != set(ids):
            raise HTTPException(400, "所选知识库不存在，请刷新后重试")
    return ids


def role_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(400, "角色名称不能为空")
    return name


@router.get("", response_model=list[RoleOut])
async def list_roles(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Role).order_by(Role.id))).all()
    return [await role_out(db, row) for row in rows]


@router.post("", response_model=RoleOut)
async def create_role(body: RoleWrite, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_admin_write(db, admin.id)
    ids = await validate_kb_ids(db, body.kb_ids)
    role = Role(name=role_name(body.name), description=body.description)
    db.add(role)
    try:
        await db.flush()
        db.add_all(RoleKnowledgeBase(role_id=role.id, kb_id=kb_id) for kb_id in ids)
        await log_audit(db, admin, "role.create", target=role.name)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "角色名称已存在或知识库已变化，请刷新后重试") from None
    return await role_out(db, role)


@router.put("/{role_id}", response_model=RoleOut)
async def update_role(role_id: int, body: RoleWrite, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_admin_write(db, admin.id)
    role = await db.get(Role, role_id, with_for_update=True)
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.system_key:
        raise HTTPException(400, "内置系统管理员角色不可修改")
    ids = await validate_kb_ids(db, body.kb_ids)
    role.name, role.description = role_name(body.name), body.description
    user_ids = list((await db.scalars(select(UserRole.user_id).where(UserRole.role_id == role.id))).all())
    try:
        await db.execute(delete(RoleKnowledgeBase).where(RoleKnowledgeBase.role_id == role.id))
        db.add_all(RoleKnowledgeBase(role_id=role.id, kb_id=kb_id) for kb_id in ids)
        await bump_user_contexts(db, user_ids)
        await log_audit(db, admin, "role.update", target=role.name, detail="更新角色与知识库授权")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "角色名称已存在或授权数据变化，请刷新后重试") from None
    return await role_out(db, role)


@router.delete("/{role_id}")
async def delete_role(role_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await lock_admin_write(db, admin.id)
    role = await db.get(Role, role_id, with_for_update=True)
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.system_key:
        raise HTTPException(409, "内置系统管理员角色不能删除")
    if await db.scalar(select(UserRole.user_id).where(UserRole.role_id == role_id).limit(1)):
        raise HTTPException(409, "该角色仍分配给用户，请先调整用户角色")
    name = role.name
    await db.delete(role)
    await log_audit(db, admin, "role.delete", target=name)
    await db.commit()
    return {"ok": True}
