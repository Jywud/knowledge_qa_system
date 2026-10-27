from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.auth import create_token, get_current_user, verify_password
from app.database import get_db
from app.models import User
from app.auth import hash_password
from app.audit import log_audit
from app.schemas import LoginRequest, PasswordChangeRequest, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_attempts: dict[str, dict] = {}


def _check_lock(username: str) -> None:
    record = _login_attempts.get(username)
    if not record:
        return
    now = datetime.now(timezone.utc)
    if record["locked_until"] and record["locked_until"] > now:
        remain = int((record["locked_until"] - now).total_seconds() // 60) + 1
        raise HTTPException(429, f"登录失败次数过多，请 {remain} 分钟后再试")


def _record_failure(username: str) -> None:
    record = _login_attempts.setdefault(
        username, {"count": 0, "locked_until": None}
    )
    record["count"] += 1
    if record["count"] >= settings.login_max_attempts:
        record["locked_until"] = datetime.now(timezone.utc) + timedelta(
            minutes=settings.login_lock_minutes
        )
        record["count"] = 0


def _reset(username: str) -> None:
    _login_attempts.pop(username, None)


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    _check_lock(body.username)
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        _record_failure(body.username)
        raise HTTPException(400, "用户名或密码错误")
    _reset(body.username)
    return {"token": create_token(user), "user": user}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.put("/password")
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")

    user.password_hash = hash_password(body.new_password)
    await log_audit(db, user, "user.change_password", target=user.username)
    await db.commit()
    return {"ok": True}
