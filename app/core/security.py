"""安全鉴权 — 保护 API 的访问控制（API Key / 多用户 JWT）。

能力：
- 校验请求头中的 API Key（常量时间比对，防时序攻击）
- 多用户模式（ENABLE_MULTIUSER=true）：账号密码哈希 + JWT 签发/校验
- 提供 FastAPI 依赖项 get_current_api_key / get_current_user，供路由层注入
  - get_current_api_key：服务/管理员/MCP/curl 用（单用户模式即 owner）
  - get_current_user：先判 X-API-Key，再判 Bearer JWT；返回当前 user_id
    （单用户模式恒为 "default"；多用户模式为 JWT 的 sub）

主要函数：
- verify_api_key(raw, expected) -> bool
- hash_password(plain) -> str / verify_password(plain, hashed) -> bool: （多用户）scrypt 哈希
- create_access_token(uid, secret) -> str: （多用户）签发 JWT（pyjwt）
- decode_jwt(token, secret) -> dict | None: JWT 解码，返回 payload
- get_current_api_key(x_api_key) -> str: FastAPI 依赖，失败抛 401
- get_current_user(x_api_key, authorization) -> str: FastAPI 依赖，返回 user_id，失败抛 401

关联方案：docs/design.md §2（core/security.py）、§8（配置与安全）、§17.3（多用户）。
"""
import base64
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings

# JWT 过期时间（秒）
_JWT_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 天


def verify_api_key(raw: str | None, expected: str) -> bool:
    """常量时间比对 API Key，防止时序攻击。

    raw 和 expected 均为空时不视为通过（空 Key 等于没鉴权）。
    """
    if not raw or not expected:
        return False
    return hmac.compare_digest(raw, expected)


async def get_current_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    """FastAPI 依赖：校验 X-API-Key，通过返回 "default"（单用户 owner）。"""
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


async def get_current_user(
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
) -> str:
    """FastAPI 依赖：先判 X-API-Key，再判 Bearer JWT，返回 user_id。"""
    # 1) X-API-Key 匹配 → 单用户 owner
    if verify_api_key(x_api_key, settings.api_key):
        return "default"

    # 2) Bearer JWT
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        payload = decode_jwt(token, settings.jwt_secret)
        if payload and payload.get("sub"):
            return payload["sub"]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或缺失的鉴权凭据",
        headers={"WWW-Authenticate": "Bearer, ApiKey"},
    )
