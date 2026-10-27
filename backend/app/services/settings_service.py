from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SystemSetting


async def get_system_settings(db: AsyncSession) -> SystemSetting:
    record = await db.get(SystemSetting, 1)
    if record:
        return record

    record = SystemSetting(
        id=1,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        top_k=settings.top_k,
    )
    db.add(record)
    await db.flush()
    return record
