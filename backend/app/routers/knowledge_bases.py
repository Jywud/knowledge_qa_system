from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user, require_admin
from app.audit import log_audit
from app.database import get_db
from app.config import BASE_DIR, settings
from app.models import Chunk, Conversation, FileRecord, KnowledgeBase, Role, RoleKnowledgeBase, User
from app.schemas import KnowledgeBaseCreate, KnowledgeBaseOut, KnowledgeBaseUpdate, RoleOut
from app.routers.roles import role_out
from app.services.permission_service import readable_kb_predicate
from app.services.document_service import delete_file_uploads, delete_file_vectors

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def _kb_out(record: KnowledgeBase, file_count: int, chunk_count: int) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=record.id,
        name=record.name,
        description=record.description or "",
        file_count=file_count,
        chunk_count=chunk_count,
        created_at=record.created_at,
    )


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    name: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(
            KnowledgeBase,
            func.count(func.distinct(FileRecord.id)),
            func.count(Chunk.id),
        )
        .outerjoin(FileRecord, FileRecord.kb_id == KnowledgeBase.id)
        .outerjoin(Chunk, Chunk.file_id == FileRecord.id)
        .group_by(KnowledgeBase.id)
        .where(readable_kb_predicate(KnowledgeBase.id, user.id))
        .order_by(KnowledgeBase.id.desc())
    )
    if name:
        stmt = stmt.where(KnowledgeBase.name.ilike(f"%{name}%"))
    result = await db.execute(stmt)
    return [_kb_out(kb, file_count, chunk_count) for kb, file_count, chunk_count in result.all()]


@router.get("/{kb_id}/roles", response_model=list[RoleOut])
async def get_kb_roles(kb_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if not await db.get(KnowledgeBase, kb_id):
        raise HTTPException(404, "知识库不存在")
    roles = (await db.scalars(select(Role).where(
        (Role.system_key == "system_admin") | Role.id.in_(
            select(RoleKnowledgeBase.role_id).where(RoleKnowledgeBase.kb_id == kb_id)))
        .order_by(Role.id))).all()
    return [await role_out(db, role) for role in roles]


@router.post("", response_model=KnowledgeBaseOut)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "知识库名称不能为空")
    exists = await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == name))
    if exists.scalar_one_or_none():
        raise HTTPException(400, f"知识库 {name} 已存在")
    kb = KnowledgeBase(name=name, description=body.description, created_by=admin.id)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    await log_audit(db, admin, "kb.create", target=kb.name)
    await db.commit()
    return _kb_out(kb, 0, 0)


@router.put("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: int,
    body: KnowledgeBaseUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "知识库名称不能为空")
    exists = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.name == name, KnowledgeBase.id != kb_id)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(400, f"知识库 {name} 已存在")
    kb.name = name
    kb.description = body.description
    await db.commit()
    await db.refresh(kb)
    return _kb_out(kb, 0, 0)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id, with_for_update=True)
    if not kb:
        raise HTTPException(404, "知识库不存在")

    conversation_id = await db.scalar(
        select(Conversation.id).where(Conversation.kb_id == kb_id).limit(1)
    )
    if conversation_id is not None:
        raise HTTPException(409, "知识库仍有关联会话，请先删除相关会话后再删除知识库")
    from app.services.conversation_scope_service import conversation_kb_ids
    multi = (await db.scalars(select(Conversation).where(Conversation.kb_id.is_(None)))).all()
    if any(kb_id in conversation_kb_ids(conv) for conv in multi):
        raise HTTPException(409, "知识库仍有关联的跨库会话，请先删除相关会话后再删除知识库")
    files = (
        await db.execute(
            select(FileRecord).where(FileRecord.kb_id == kb_id)
            .order_by(FileRecord.id).with_for_update()
        )
    ).scalars().all()
    if any(record.status == "processing" for record in files):
        raise HTTPException(409, "知识库有文件正在后台处理中，请稍后再删除")
    file_ids = [record.id for record in files]
    try:
        for record in files:
            await delete_file_vectors(db, record.id)
            await db.delete(record)
        await db.delete(kb)
        await log_audit(db, admin, "kb.delete", target=kb.name)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "知识库仍有关联数据，请刷新后重试") from None
    for file_id in file_ids:
        delete_file_uploads(BASE_DIR / settings.upload_dir, file_id)
    return {"ok": True}
