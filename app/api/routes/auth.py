"""API·auth — 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）。

能力：
- 探测鉴权模式（mode，免鉴权，供前端决定进入方式）
- 注册账号（register）
- 登录签发 JWT（login）
- 取当前用户（me，调试 / 前端取身份）

主要端点：
- GET  /api/v1/auth/mode      -> { multiuser, api_key_required }
- POST /api/v1/auth/register  { username, password } -> UserOut
- POST /api/v1/auth/login     { username, password } -> Token
- GET  /api/v1/auth/me        -> UserOut

关联方案：docs/design.md §17.3（多用户）、§8（配置与安全）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.models.schemas import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _require_multiuser() -> None:
    """多用户模式未开启时直接 403。"""
    if not settings.enable_multiuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="多用户模式未启用",
        )


def _require_jwt_secret() -> str:
    """JWT 密钥未配置时直接 500。"""
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务端未配置 JWT_SECRET",
        )
    return settings.jwt_secret


@router.get("/mode")
async def auth_mode() -> dict:
    """探测鉴权模式（**免鉴权**）。

    前端启动时先调这里，据此决定进入方式：
      · multiuser=False 且 api_key_required=False → 本机免鉴权，直接进主界面
      · multiuser=False 且 api_key_required=True  → 让用户填一次 API Key
      · multiuser=True                            → 强制弹登录 / 注册

    只返回两个布尔位，不含任何凭据。
    """
    return {
        "multiuser": settings.enable_multiuser,
        "api_key_required": bool(settings.api_key) and not settings.enable_multiuser,
    }


@router.post("/register", response_model=UserOut)
async def register(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    """注册新账号（仅多用户模式）。"""
    _require_multiuser()
    _require_jwt_secret()

    # 查重 username
    existing = await session.execute(
        select(User).where(User.username == payload.username)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"用户名已存在: {payload.username}",
        )

    # 创建用户（uid 自动生成）
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info("用户注册", uid=user.uid, username=user.username)
    return UserOut(uid=user.uid, username=user.username, is_admin=user.is_admin)


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    """登录签发 JWT（仅多用户模式）。"""
    _require_multiuser()
    secret = _require_jwt_secret()

    result = await session.execute(
        select(User).where(User.username == payload.username)
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.uid, secret)
    logger.info("用户登录", uid=user.uid, username=user.username)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """返回当前用户信息。

    单用户模式返回合成用户（uid="default", username="default"）；
    多用户模式从数据库按 uid 查找。
    """
    if user_id == "default":
        return UserOut(uid="default", username="default", is_admin=True)

    # 多用户模式：user_id 是 JWT sub（user.uid）
    result = await session.execute(select(User).where(User.uid == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    return UserOut(uid=user.uid, username=user.username, is_admin=user.is_admin)
