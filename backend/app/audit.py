from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


async def log_audit(
    db: AsyncSession, operator: User, action: str, target: str = "", detail: str = ""
) -> None:
    db.add(
        AuditLog(
            operator_id=operator.id,
            operator_name=operator.username,
            action=action,
            target=target,
            detail=detail,
        )
    )
