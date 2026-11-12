from fastapi import HTTPException
from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, KnowledgeBase, Role, RoleKnowledgeBase, User, UserRole

SYSTEM_ADMIN = "system_admin"


def admin_predicate(user_id: int):
    return exists(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(
        UserRole.user_id == user_id, Role.system_key == SYSTEM_ADMIN))


def readable_kb_predicate(column, user_id: int):
    return or_(admin_predicate(user_id), column.in_(
        select(RoleKnowledgeBase.kb_id).join(UserRole, UserRole.role_id == RoleKnowledgeBase.role_id)
        .where(UserRole.user_id == user_id)))


async def is_system_admin(db: AsyncSession, user_id: int) -> bool:
    return bool(await db.scalar(select(admin_predicate(user_id))))


async def require_kb_read(db: AsyncSession, user_id: int, kb_id: int | None) -> None:
    if kb_id is None or not await db.scalar(select(KnowledgeBase.id).where(
        KnowledgeBase.id == kb_id, readable_kb_predicate(KnowledgeBase.id, user_id))):
        raise HTTPException(404, "知识库不存在或没有访问权限")


async def authorization_lock(db: AsyncSession, *, write: bool = False) -> Role:
    role = await db.scalar(select(Role).where(Role.system_key == SYSTEM_ADMIN)
                           .with_for_update(read=not write))
    if not role:
        raise HTTPException(503, "角色权限尚未初始化")
    return role


async def public_user(db: AsyncSession, user: User) -> dict:
    roles = (await db.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id)
                             .where(UserRole.user_id == user.id).order_by(Role.id))).all()
    return {"id": user.id, "username": user.username,
            "roles": [{"id": role.id, "name": role.name, "system_key": role.system_key} for role in roles],
            "is_admin": any(role.system_key == SYSTEM_ADMIN for role in roles)}


async def bump_user_contexts(db: AsyncSession, user_ids: list[int]) -> None:
    if user_ids:
        await db.execute(update(Conversation).where(Conversation.user_id.in_(user_ids))
                         .values(memory_epoch=Conversation.memory_epoch + 1, memory_thread_id=None))
