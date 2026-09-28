"""安全鉴权 — 保护 API 的访问控制（API Key / 多用户 JWT）。

能力：
- 校验请求头中的 API Key（常量时间比对，防时序攻击）
- 多用户模式（ENABLE_MULTIUSER=true）：账号密码哈希 + JWT 签发/校验
- 用户级 API Key（api_keys 表，M06 §5.7）：生成 / 哈希工具 + 鉴权链第 2 段
- 提供 FastAPI 依赖项 get_current_api_key / get_current_user，供路由层注入
  - get_current_api_key：服务/管理员/MCP/curl 用（单用户模式即 owner）
  - get_current_user：三段式鉴权链 —— 全局 X-API-Key → 用户级 API Key →
    Bearer JWT；返回当前 user_id（单用户模式恒为 "default"）

主要函数：
- verify_api_key(raw, expected) -> bool
- hash_password(plain) -> str / verify_password(plain, hashed) -> bool: （多用户）scrypt 哈希
- create_access_token(uid, secret) -> str: （多用户）签发 JWT（pyjwt）
- decode_jwt(token, secret) -> dict | None: JWT 解码，返回 payload
- get_current_api_key(x_api_key) -> str: FastAPI 依赖，失败抛 401
- get_current_user(x_api_key, authorization, session) -> str: FastAPI 依赖，返回 user_id，失败抛 401
- resolve_user_id(session, x_api_key, authorization) -> str | None: 三段式鉴权链的
  无人格版本（无 FastAPI 依赖），供 MCP 等非 HTTP 入口复用；识别不出返回 None

注意：用户级 key 的生成（generate_api_key）与哈希（hash_api_key）定义在
app/models/api_key.py，与 ORM 同文件 —— 它们是 key 的「数据不变式」，放一起。

关联方案：docs/design.md §2（core/security.py）、§8（配置与安全）、§17.3（多用户）。
"""
import base64
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.api_key import hash_api_key
from app.repositories import api_key_repo

# JWT 过期时间（秒）
_JWT_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 天


def verify_api_key(raw: str | None, expected: str) -> bool:
    """常量时间比对 API Key，防止时序攻击。

    raw 和 expected 均为空时不视为通过（空 Key 等于没鉴权）。
    """
    if not raw or not expected:
        return False
    return hmac.compare_digest(raw, expected)


def _open_access() -> bool:
    """是否处于「本机免鉴权」状态：单用户模式且未配置 API_KEY（见 §17.3）。

    单用户模式本就是单机自用场景，默认不配 key；此时若仍强制 X-API-Key，
    前端就必须发明一套凭据录入流程，与「后台默认登录」的目标相悖。
    多用户模式**不适用**本捷径 —— 那里必须凭账号登录，否则会绕过用户隔离。
    """
    return not settings.enable_multiuser and not settings.api_key


async def get_current_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    """FastAPI 依赖：校验 X-API-Key，通过返回 "default"（单用户 owner）。"""
    if _open_access():
        return "default"

    if not verify_api_key(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或缺失的 API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return "default"


# ===== 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）=====


def hash_password(plain: str) -> str:
    """scrypt 哈希密码，返回 "scrypt$<salt_b64>$<hash_b64>" 格式字符串。"""
    salt = os.urandom(16)
    derived = hashlib.scrypt(plain.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(derived).decode()
    return f"scrypt${salt_b64}${hash_b64}"


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与 scrypt 哈希是否匹配。"""
    try:
        algo, salt_b64, hash_b64 = hashed.split("$", 2)
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(plain.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(derived, expected)
    except (ValueError, AttributeError):
        return False


def create_access_token(uid: str, secret: str) -> str:
    """签发 JWT，payload 中 sub=uid，默认 7 天过期。"""
    payload = {
        "sub": uid,
        "iat": int(time.time()),
        "exp": int(time.time()) + _JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict | None:
    """解码并校验 JWT，失败返回 None。"""
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


async def resolve_user_id(
    session: AsyncSession,
    x_api_key: str | None = None,
    authorization: str | None = None,
) -> str | None:
    """三段式鉴权链的「无人格」版本：识别成功返回 user_id，识别不出返回 None。

    与 get_current_user 共用同一份逻辑（后者只多了「失败抛 401」这一步）。
    之所以拆出来，是因为 MCP 接入（stdio / Streamable HTTP）不走 FastAPI 依赖，
    无法复用 HTTPException —— 两条入口共用本函数可避免鉴权规则各写一份而漂移。

    判定顺序（M06 §5.7）：
      0) 单用户且未配 Key → 本机免鉴权，返回 "default"
      1) X-API-Key 匹配**全局** settings.api_key → "default"（单用户 owner）
      2) X-API-Key 命中 api_keys 表（用户级 key，agent 接入）→ 该 key 的 user_id
         —— key 明文永不入库，按 sha256(key) 查唯一索引；命中即天然常数时间
         （比较发生在 hash 之后的索引查找上，无时序泄露面）
      3) Bearer JWT → payload["sub"]

    顺序有讲究：全局 key 在前（一次内存比对，零开销），
    用户级 key 居中（一次 DB 查询），JWT 最后（需要解码验签）。
    """
    # 0) 单用户且未配 Key：本机免鉴权（前端无需任何凭据即可进入）
    if _open_access():
        return "default"

    # 1) X-API-Key 匹配全局 key → 单用户 owner
    if verify_api_key(x_api_key, settings.api_key):
        return "default"

    # 2) 用户级 API Key（api_keys 表，供 agent / 第三方接入；M06 §5.7）
    #    注意与步骤 1 的区别：这里能区分出「是谁」，返回 key 归属的 user_id
    if x_api_key:
        key_row = await api_key_repo.find_active_by_hash(
            session, hash_api_key(x_api_key)
        )
        if key_row is not None:
            await api_key_repo.touch_api_key(session, key_row.id)
            await session.commit()
            return key_row.user_id

    # 3) Bearer JWT
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        payload = decode_jwt(token, settings.jwt_secret)
        if payload and payload.get("sub"):
            return payload["sub"]

    return None


async def get_current_user(
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
) -> str:
    """FastAPI 依赖：三段式鉴权链，返回 user_id；识别不出统一 401。"""
    user_id = await resolve_user_id(
        session, x_api_key=x_api_key, authorization=authorization
    )
    if user_id is not None:
        return user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或缺失的鉴权凭据",
        headers={"WWW-Authenticate": "Bearer, ApiKey"},
    )
