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

    record = await get_system_settings(db)
    record.chunk_size = body.chunk_size
    record.chunk_overlap = body.chunk_overlap
    record.top_k = body.top_k
    await db.commit()
    await db.refresh(record)
    return record
