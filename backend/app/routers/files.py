from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_DIR, settings
from app.auth import get_current_user, require_admin
from app.audit import log_audit
from app.database import get_db
from app.models import Chunk, FileRecord, KnowledgeBase, User
from app.schemas import ChunkOut, FileOut
from app.services.document_service import (
    SUPPORTED_TYPES,
    delete_file_vectors,
    process_file_record,
)

router = APIRouter(prefix="/api/files", tags=["files"])


def _upload_dir() -> Path:
    path = BASE_DIR / settings.upload_dir
    path.mkdir(exist_ok=True)
    return path


def _file_out(record: FileRecord, chunk_count: int, uploader: str = "") -> FileOut:
    return FileOut(
        id=record.id,
        kb_id=record.kb_id,
        filename=record.filename,
        file_type=record.file_type,
        size=record.size,
        version=record.version,
        status=record.status,
        status_message=record.status_message or "",
        chunk_count=chunk_count,
        uploader=uploader,
        created_at=record.created_at,
    )


@router.post("", response_model=FileOut)
async def upload_file(
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    file: UploadFile = File(...),
    kb_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    suffix = Path(file.filename).suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，仅支持 md/docx/pdf/txt")

    record = FileRecord(
        kb_id=kb_id,
        filename=file.filename,
        file_type=suffix,
        status="processing",
        uploaded_by=admin.id,
    )
    db.add(record)
    await db.flush()

    save_path = _upload_dir() / f"{record.id}_{file.filename}"
    async with aiofiles.open(save_path, "wb") as out:
        content = await file.read()
        await out.write(content)
    record.size = len(content)

    await log_audit(db, admin, "file.upload", target=file.filename)
    await db.commit()
    await db.refresh(record)
    background_tasks.add_task(
        process_file_record, record.id, save_path, suffix, file.filename, kb_id
    )
    return _file_out(record, 0, admin.username)


@router.get("", response_model=list[FileOut])
async def list_files(
    kb_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(FileRecord, func.count(Chunk.id), User.username)
        .outerjoin(Chunk, Chunk.file_id == FileRecord.id)
        .join(User, User.id == FileRecord.uploaded_by)
        .group_by(FileRecord.id, User.username)
        .order_by(FileRecord.id.desc())
    )
    if kb_id:
        stmt = stmt.where(FileRecord.kb_id == kb_id)
    result = await db.execute(stmt)
    return [_file_out(record, count, username) for record, count, username in result.all()]


@router.get("/{file_id}/chunks", response_model=list[ChunkOut])
async def get_chunks(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Chunk).where(Chunk.file_id == file_id).order_by(Chunk.chunk_index)
    )
    return result.scalars().all()


@router.put("/{file_id}", response_model=FileOut)
async def update_file(
    file_id: int,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(404, "文件不存在")
    if record.status == "processing":
        raise HTTPException(409, "文件正在后台处理中，请稍后再试")
    suffix = Path(file.filename).suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，仅支持 md/docx/pdf/txt")

    await delete_file_vectors(db, file_id)

    save_path = _upload_dir() / f"{file_id}_{file.filename}"
    async with aiofiles.open(save_path, "wb") as out:
        content = await file.read()
        await out.write(content)

    record.filename = file.filename
    record.file_type = suffix
    record.size = len(content)
    record.version += 1
    record.status = "processing"
    record.status_message = None
    await db.commit()
    await db.refresh(record)
    background_tasks.add_task(
        process_file_record, file_id, save_path, suffix, file.filename, record.kb_id
    )
    return _file_out(record, 0, admin.username)


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(404, "文件不存在")
    if record.status == "processing":
        raise HTTPException(409, "文件正在后台处理中，无法删除")

    await delete_file_vectors(db, file_id)
    await db.delete(record)
    await log_audit(db, admin, "file.delete", target=record.filename)
    await db.commit()

    for path in _upload_dir().glob(f"{file_id}_*"):
        path.unlink(missing_ok=True)
    return {"ok": True}
