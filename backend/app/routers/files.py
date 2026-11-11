from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

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
    delete_file_uploads,
    process_file_record,
    process_file_update,
)

router = APIRouter(prefix="/api/files", tags=["files"])
logger = logging.getLogger(__name__)


def _upload_dir() -> Path:
    path = BASE_DIR / settings.upload_dir
    path.mkdir(exist_ok=True)
    return path


def _safe_filename(filename: str | None) -> str:
    raw = (filename or "").replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(ch for ch in raw if ch.isprintable() and ch not in ':*?"<>|')
    cleaned = cleaned.strip(". ") or "unnamed"
    return cleaned[:128]


async def _save_upload(file: UploadFile, dest: Path) -> int:
    limit = settings.max_upload_mb * 1024 * 1024
    total = 0
    try:
        async with aiofiles.open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, f"文件大小超过限制（{settings.max_upload_mb} MB）")
                await out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return total


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
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，仅支持 md/docx/pdf/txt")

    record = FileRecord(
        kb_id=kb_id,
        filename=filename,
        file_type=suffix,
        status="processing",
        uploaded_by=admin.id,
    )
    db.add(record)
    await db.flush()

    save_path = _upload_dir() / f"{record.id}_{filename}"
    record.size = await _save_upload(file, save_path)

    await log_audit(db, admin, "file.upload", target=filename)
    await db.commit()
    await db.refresh(record)
    background_tasks.add_task(
        process_file_record, record.id, save_path, suffix, filename, kb_id
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
    record = await db.get(FileRecord, file_id, with_for_update=True)
    if not record:
        raise HTTPException(404, "文件不存在")
    if record.status == "processing":
        raise HTTPException(409, "文件正在后台处理中，请稍后再试")
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，仅支持 md/docx/pdf/txt")

    pending_dir = _upload_dir() / ".pending"
    pending_dir.mkdir(exist_ok=True)
    save_path = pending_dir / f"{uuid4().hex}.{suffix}"
    version = record.version
    original_status = record.status
    processing_at = datetime.now(timezone.utc).replace(tzinfo=None)
    commit_attempted = False
    chunk_count = await db.scalar(select(func.count(Chunk.id)).where(Chunk.file_id == file_id))
    try:
        size = await _save_upload(file, save_path)
        record.status = "processing"
        record.status_message = None
        record.updated_at = processing_at
        commit_attempted = True
        await db.commit()
    except BaseException:
        can_remove = not commit_attempted
        if commit_attempted:
            from app.database import SessionLocal

            try:
                await db.rollback()
                async with SessionLocal() as recovery_db:
                    current = await recovery_db.get(FileRecord, file_id, with_for_update=True)
                    if (current and current.version == version and current.status == "processing"
                            and current.updated_at == processing_at):
                        current.status = original_status
                        current.status_message = "更新提交失败，已保留原版本，请重试"
                        await recovery_db.commit()
                can_remove = True
            except Exception:
                logger.exception("文件 %s 更新提交状态无法核实，保留暂存文件", file_id)
        if can_remove:
            save_path.unlink(missing_ok=True)
        raise
    background_tasks.add_task(
        process_file_update, file_id, save_path, suffix, filename, size, version
    )
    return _file_out(record, chunk_count, admin.username)


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(FileRecord, file_id, with_for_update=True)
    if not record:
        raise HTTPException(404, "文件不存在")
    if record.status == "processing":
        raise HTTPException(409, "文件正在后台处理中，无法删除")

    await delete_file_vectors(db, file_id)
    await db.delete(record)
    await log_audit(db, admin, "file.delete", target=record.filename)
    await db.commit()

    delete_file_uploads(_upload_dir(), file_id)
    return {"ok": True}
