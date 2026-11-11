from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user, hash_password, require_admin
from app.audit import log_audit
from app.database import get_db
from app.models import AuditLog, Conversation, FileRecord, KnowledgeBase, User
from app.schemas import CreateUserRequest, PasswordResetRequest, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.post("", response_model=UserOut)
async def create_user(
    body: CreateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(select(User).where(User.username == body.username))
    if exists.scalar_one_or_none():
        raise HTTPException(400, f"用户名 {body.username} 已存在")
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "角色只能是 admin 或 user")
    user = User(
        username=body.username,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await log_audit(db, admin, "user.create", target=user.username)
    await db.commit()
    return user


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
    user = await db.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(404, "用户不存在")
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
