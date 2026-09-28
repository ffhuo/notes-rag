"""API·auth — 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）+ 用户级 API Key。

能力：
- 探测鉴权模式（mode，免鉴权，供前端决定进入方式）
- 注册账号（register）
- 登录签发 JWT（login）
- 取当前用户（me，调试 / 前端取身份）
- 用户级 API Key 管理（M06 §5.7）：创建 / 列表 / 撤销，供 agent / 第三方接入

主要端点：
- GET    /api/v1/auth/mode             -> { multiuser, api_key_required }
- POST   /api/v1/auth/register         { username, password } -> UserOut
- POST   /api/v1/auth/login            { username, password } -> Token
- GET    /api/v1/auth/me               -> UserOut
- POST   /api/v1/auth/api-keys         { name } -> ApiKeyCreated（**明文仅此一次**，201）
- GET    /api/v1/auth/api-keys         -> list[ApiKeyOut]（含已撤销，永不含明文）
- DELETE /api/v1/auth/api-keys/{key_id} -> 204（撤销 = 软删除，立即失效）

关联方案：M06 §5.7（用户级 API Key / agent 接入）、§17.3（多用户）、M02（api_keys 表）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from loguru import logger

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.models.api_key import generate_api_key, hash_api_key
from app.models.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    Token,
    UserCreate,
    UserOut,
)
from app.repositories import api_key_repo

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


# ===== 用户级 API Key（agent / 第三方接入鉴权，M06 §5.7）=====


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """为本用户签发一个新 API Key。

    **明文 key 只在本响应出现一次**（ApiKeyCreated.key），服务端只存 sha256；
    关闭弹窗后无法再查看，丢失只能撤销重建（与 GitHub token 同策略）。

    该 key 的数据隔离与当前用户完全一致 —— agent 持 key 调用任何接口，
    身份即为本用户（见 security.get_current_user 鉴权链第 2 段）。
    """
    raw = generate_api_key()
    row = await api_key_repo.create_api_key(
        session,
        user_id=user_id,
        name=payload.name,
        key_hash=hash_api_key(raw),
        key_prefix=raw[:11],  # "nr_" + 前 8 字符，供列表识别
    )
    await session.commit()
    await session.refresh(row)

    logger.info("创建用户级 API Key", uid=user_id, key_id=row.id, name=payload.name)
    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        key=raw,
    )


@router.get("/api-keys", response_model=List[ApiKeyOut])
async def list_api_keys(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出本用户的全部 API Key（含已撤销，**永不含明文**）。"""
    rows = await api_key_repo.list_api_keys(session, user_id)
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            key_prefix=r.key_prefix,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """撤销 API Key（软删除，立即失效；记录保留供审计）。"""
    found = await api_key_repo.revoke_api_key(session, user_id, key_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key 不存在或不属于当前用户: {key_id}",
        )
    await session.commit()
    logger.info("撤销用户级 API Key", uid=user_id, key_id=key_id)
