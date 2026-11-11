import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User


def validate_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    if len(username) > 64:
        raise HTTPException(400, "用户名不能超过 64 个字符")
    return username


def validate_new_password(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if len(password) > 128:
        raise HTTPException(400, "密码不能超过 128 位")
    if not password.strip():
        raise HTTPException(400, "密码不能全部为空白字符")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return hmac.compare_digest(calc.hex(), digest)


def _password_version(user: User) -> str:
    return hmac.new(
        settings.jwt_secret.encode(),
        f"password-version:{user.password_hash or ''}".encode(),
        hashlib.sha256,
    ).hexdigest()


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
        "pwd_ver": _password_version(user),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    try:
        payload = jwt.decode(
            header[7:], settings.jwt_secret, algorithms=["HS256"],
            options={"require": ["sub", "exp", "pwd_ver"]},
        )
        user_id = int(payload["sub"])
        if not isinstance(payload["pwd_ver"], str) or not payload["pwd_ver"].isascii():
            raise ValueError("invalid password version")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(401, "登录已过期，请重新登录")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    if not hmac.compare_digest(payload["pwd_ver"], _password_version(user)):
        raise HTTPException(401, "密码已变更，请重新登录")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可执行该操作")
    return user
