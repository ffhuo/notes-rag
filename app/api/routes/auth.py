"""API·auth — 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）。

能力：
- 注册账号（register）
- 登录签发 JWT（login）
- 取当前用户（me，调试 / 前端取身份）

主要端点：
- POST /api/v1/auth/register  { username, password } -> UserOut
- POST /api/v1/auth/login     { username, password } -> Token
- GET  /api/v1/auth/me        -> UserOut

关联方案：docs/design.md §17.3（多用户）、§8（配置与安全）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.database import get_session
from app.core.security import create_access_token, decode_jwt, hash_password, verify_password
from app.models.schemas import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
async def register(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    # 1) 查重 username → 2) hash_password → 3) vault_repo.create_user
    ...


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    # 1) get_user_by_username → 2) verify_password → 3) create_access_token(user_id)
    ...


@router.get("/me", response_model=UserOut)
async def me(user_id: str = Depends(get_current_user_id)):
    # 返回当前用户（单用户模式 user_id="default"，可返回合成用户）
    ...
