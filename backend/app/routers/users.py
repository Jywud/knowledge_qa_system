from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user, hash_password, require_admin, validate_new_password, validate_username
from app.audit import log_audit
from app.database import get_db
from app.models import AuditLog, Conversation, FileRecord, KnowledgeBase, Role, User, UserRole
from app.schemas import CreateUserRequest, PasswordResetRequest, UserOut, UserRolesUpdate
from app.routers.roles import lock_admin_write
from app.services.permission_service import bump_user_contexts, public_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await public_user(db, user)


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.id))
    return [await public_user(db, row) for row in result.scalars().all()]


async def validate_roles(db: AsyncSession, values: list[int]) -> list[int]:
    ids = sorted(set(values))
    found = (await db.scalars(select(Role.id).where(Role.id.in_(ids)))).all()
    if not ids or set(ids) != set(found):
        raise HTTPException(400, "请选择有效角色")
    return ids


@router.post("", response_model=UserOut)
async def create_user(
    body: CreateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    username = validate_username(body.username)
    validate_new_password(body.password)
    await lock_admin_write(db, admin.id)
    role_ids = await validate_roles(db, body.role_ids)
    exists = await db.execute(select(User).where(User.username == username))
    if exists.scalar_one_or_none():
        raise HTTPException(400, f"用户名 {username} 已存在")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        await db.flush()
        db.add_all(UserRole(user_id=user.id, role_id=role_id) for role_id in role_ids)
        await log_audit(db, admin, "user.create", target=user.username)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "用户名已存在或角色已变化，请刷新后重试") from None
    return await public_user(db, user)


@router.put("/{user_id}/roles", response_model=UserOut)
async def assign_roles(user_id: int, body: UserRolesUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    guardian = await lock_admin_write(db, admin.id)
    target = await db.get(User, user_id, with_for_update=True)
    if not target:
        raise HTTPException(404, "用户不存在")
    ids = await validate_roles(db, body.role_ids)
    was_admin = await db.get(UserRole, (user_id, guardian.id)) is not None
    if was_admin and guardian.id not in ids:
        count = await db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == guardian.id))
        if count <= 1:
            raise HTTPException(409, "至少保留一名系统管理员")
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add_all(UserRole(user_id=user_id, role_id=role_id) for role_id in ids)
    await bump_user_contexts(db, [user_id])
    await log_audit(db, admin, "user.assign_roles", target=target.username, detail="调整用户角色")
    await db.commit()
    return await public_user(db, target)


@router.put("/{user_id}/password")
async def reset_password(
    user_id: int,
    body: PasswordResetRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    validate_new_password(body.password)
    user.password_hash = hash_password(body.password)
    await log_audit(db, admin, "user.reset_password", target=user.username)
    await db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(400, "不能删除自己")
    guardian = await lock_admin_write(db, admin.id)
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(404, "用户不存在")
    if await db.get(UserRole, (user_id, guardian.id)):
        count = await db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == guardian.id))
        if count <= 1:
            raise HTTPException(409, "至少保留一名系统管理员")
    references = (
        (KnowledgeBase.created_by, "创建的知识库"),
        (FileRecord.uploaded_by, "上传的文件"),
        (Conversation.user_id, "会话记录"),
        (AuditLog.operator_id, "审计记录"),
    )
    for column, label in references:
        if await db.scalar(select(column).where(column == user_id).limit(1)) is not None:
            raise HTTPException(409, f"用户仍有{label}，为保留关联数据暂不能删除")
    try:
        await db.delete(user)
        await log_audit(db, admin, "user.delete", target=user.username)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "用户仍有关联数据，请刷新后重试") from None
    return {"ok": True}
