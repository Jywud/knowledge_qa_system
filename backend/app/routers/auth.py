from fastapi import APIRouter, Depends, HTTPException, Request, Response
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.auth import create_token, get_current_user, verify_password
from app.database import get_db
from app.models import User
from app.auth import hash_password, validate_new_password
from app.audit import log_audit
from app.schemas import LoginOut, LoginRequest, PasswordChangeRequest, UserOut
from app.services.permission_service import public_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_attempts: OrderedDict[str, dict] = OrderedDict()
_MAX_LOGIN_SOURCES = 4096


def _prune_attempts(now: datetime) -> None:
    for source, record in list(_login_attempts.items()):
        if record["expires_at"] <= now:
            _login_attempts.pop(source, None)


def _check_lock(source: str) -> None:
    now = datetime.now(timezone.utc)
    _prune_attempts(now)
    record = _login_attempts.get(source)
    if not record:
        return
    if record["locked_until"] and record["locked_until"] > now:
        remain = int((record["locked_until"] - now).total_seconds() // 60) + 1
        raise HTTPException(429, f"登录失败次数过多，请 {remain} 分钟后再试")


def _record_failure(source: str) -> None:
    now = datetime.now(timezone.utc)
    _prune_attempts(now)
    if source not in _login_attempts:
        if len(_login_attempts) >= _MAX_LOGIN_SOURCES:
            _login_attempts.popitem(last=False)
        _login_attempts[source] = {"count": 0, "locked_until": None,
            "expires_at": now + timedelta(minutes=settings.login_lock_minutes)}
    _login_attempts.move_to_end(source)
    record = _login_attempts[source]
    record["count"] += 1
    if record["count"] >= settings.login_max_attempts:
        record["locked_until"] = now + timedelta(
            minutes=settings.login_lock_minutes
        )
        record["expires_at"] = record["locked_until"]


@router.post("/login", response_model=LoginOut)
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # 由 run.py 限定可信代理，入口代理必须覆盖外部传入的来源头。
    source = request.client.host if request.client else "unknown"
    _check_lock(source)
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        _record_failure(source)
        raise HTTPException(400, "用户名或密码错误")
    # 成功登录不清共享来源的失败预算，避免用已知账号重置猜密次数。
    response.headers["Cache-Control"] = "no-store"
    return {"token": create_token(user), "user": await public_user(db, user)}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await public_user(db, user)


@router.put("/password")
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    validate_new_password(body.new_password)
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")

    user.password_hash = hash_password(body.new_password)
    await log_audit(db, user, "user.change_password", target=user.username)
    await db.commit()
    return {"ok": True}
