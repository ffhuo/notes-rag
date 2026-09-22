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
- hash_password(plain) -> str / verify_password(plain, hashed) -> bool: （多用户）密码哈希，建议 bcrypt/scrypt
- create_access_token(user_id, secret) -> str: （多用户）签发 JWT（依赖 pyjwt）
- decode_jwt(token, secret) -> dict | None: JWT 解码，返回 payload
- get_current_api_key(x_api_key) -> str: FastAPI 依赖，失败抛 401
- get_current_user(x_api_key, authorization) -> str: FastAPI 依赖，返回 user_id，失败抛 401

关联方案：docs/design.md §2（core/security.py）、§8（配置与安全）、§17.3（多用户）。
"""
from fastapi import Header, HTTPException, status
import hmac


def verify_api_key(raw: str | None, expected: str) -> bool:
    ...


async def get_current_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    ...


# ===== 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）=====
# 密码哈希建议用 bcrypt / scrypt（passlib 或 stdlib hashlib.scrypt）；JWT 用 pyjwt。
def hash_password(plain: str) -> str:
    ...


def verify_password(plain: str, hashed: str) -> bool:
    ...


def create_access_token(user_id: str, secret: str) -> str:
    # 使用 pyjwt 签发，payload={"sub": user_id}，设置过期时间
    ...


def decode_jwt(token: str, secret: str) -> dict | None:
    ...


async def get_current_user(
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
) -> str:
    # 1) 若 X-API-Key 匹配 settings.api_key → 返回 "default"（单用户 owner / 服务调用）
    # 2) 否则解析 Authorization: Bearer <JWT> → decode_jwt → 返回 sub
    # 3) 都不通过 → 401
    ...
