"""会话的固定检索范围与当前授权必须同时满足，不能由客户端或 Checkpoint 扩大。"""
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, KnowledgeBase
from app.services.permission_service import readable_kb_predicate


def conversation_kb_ids(conv: Conversation) -> list[int]:
    if conv.kb_id is not None:
        return [conv.kb_id] if conv.kb_id > 0 else []
    try:
        values = json.loads(conv.kb_scope or "null")
    except (ValueError, TypeError):
        return []
    if not isinstance(values, list) or not values or any(
        type(value) is not int or value <= 0 for value in values
    ):
        return []
    return sorted(set(values))


async def readable_kb_ids(db: AsyncSession, user_id: int) -> set[int]:
    return set((await db.scalars(select(KnowledgeBase.id).where(
        readable_kb_predicate(KnowledgeBase.id, user_id)))).all())


async def create_scope(db: AsyncSession, user_id: int, kb_id: int | None) -> list[int]:
    if kb_id is not None and (type(kb_id) is not int or kb_id <= 0):
        raise HTTPException(400, "知识库范围无效")
    statement = select(KnowledgeBase.id).where(readable_kb_predicate(KnowledgeBase.id, user_id))
    if kb_id is not None:
        statement = statement.where(KnowledgeBase.id == kb_id)
    ids = list((await db.scalars(statement.order_by(KnowledgeBase.id)
                               .with_for_update(read=True, key_share=True))).all())
    if not ids:
        raise HTTPException(404 if kb_id is not None else 403,
                            "知识库不存在或没有访问权限" if kb_id is not None else "暂无可访问的知识库，请联系管理员分配角色")
    return ids


async def require_conversation_scope(db: AsyncSession, user_id: int, conv: Conversation) -> list[int]:
    scope = conversation_kb_ids(conv)
    if not scope:
        raise HTTPException(404, "会话检索范围无效，请新建会话")
    allowed = set((await db.scalars(select(KnowledgeBase.id).where(
        KnowledgeBase.id.in_(scope), readable_kb_predicate(KnowledgeBase.id, user_id)))).all())
    if not set(scope).issubset(allowed):
        raise HTTPException(404, "会话涉及的知识库不存在或没有访问权限，请新建会话")
    return scope
