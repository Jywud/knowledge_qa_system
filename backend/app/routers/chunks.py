from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Chunk, FileRecord, User
from app.schemas import ChunkDetailOut

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


def _unavailable(status: int, detail: str) -> HTTPException:
    return HTTPException(status, detail, headers={"Cache-Control": "no-store"})


@router.get("/{chunk_id}", response_model=ChunkDetailOut)
async def get_chunk(
    response: Response,
    chunk_id: int = Path(gt=0),
    file_id: int | None = Query(default=None, gt=0),
    version: int | None = Query(default=None, gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChunkDetailOut:
    result = await db.execute(
        select(
            Chunk.id, Chunk.file_id, Chunk.chunk_index, Chunk.page_no, Chunk.content,
            FileRecord.version.label("file_version"), FileRecord.filename, FileRecord.file_type,
        ).join(FileRecord, FileRecord.id == Chunk.file_id)
        .where(Chunk.id == chunk_id)
    )
    row = result.first()
    if row is None:
        record = await db.get(FileRecord, file_id) if file_id is not None else None
        if record is not None and version is not None and record.version != version:
            raise _unavailable(410, "原文件已更新，此引用已失效")
        raise _unavailable(404, "原文片段已不存在，文件可能已更新或删除")

    if file_id is not None and row.file_id != file_id:
        raise _unavailable(404, "引用片段不属于该文件")
    if version is not None and row.file_version != version:
        raise _unavailable(410, "原文件已更新，此引用已失效")

    response.headers["Cache-Control"] = "no-store"
    return ChunkDetailOut(**row._mapping)
