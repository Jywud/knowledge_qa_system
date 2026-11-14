from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models import User
from app.schemas import SystemSettingOut, SystemSettingUpdate
from app.services.settings_service import get_system_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SystemSettingOut)
async def get_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await get_system_settings(db)


@router.put("", response_model=SystemSettingOut)
async def update_settings(
    body: SystemSettingUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.chunk_size < 100:
        raise HTTPException(400, "分块大小不能小于 100")
    if body.chunk_overlap < 0:
        raise HTTPException(400, "重叠窗口不能小于 0")
    if body.chunk_overlap >= body.chunk_size:
        raise HTTPException(400, "重叠窗口必须小于分块大小")
    if body.top_k < 1:
        raise HTTPException(400, "TopK 不能小于 1")
    if body.rrf_top_n < 1:
        raise HTTPException(400, "融合保留条数不能小于 1")
    if body.top_n < 1:
        raise HTTPException(400, "重排保留条数不能小于 1")
    if body.top_n > body.rrf_top_n:
        raise HTTPException(400, "重排保留条数不能大于融合保留条数")
    if not 0 <= body.retrieval_min_score <= 1:
        raise HTTPException(400, "相似度阈值需在 0 到 1 之间")

    record = await get_system_settings(db)
    record.chunk_size = body.chunk_size
    record.chunk_overlap = body.chunk_overlap
    record.top_k = body.top_k
    record.rerank_enabled = body.rerank_enabled
    record.rrf_top_n = body.rrf_top_n
    record.top_n = body.top_n
    record.retrieval_min_score = body.retrieval_min_score
    await db.commit()
    await db.refresh(record)
    return record
