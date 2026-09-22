"""安全鉴权 — 保护 API 的访问控制（API Key / 可选 JWT）。

能力：
- 校验请求头中的 API Key（常量时间比对，防时序攻击）
- 可选：解析并校验 JWT，返回 payload
- 提供 FastAPI 依赖项 get_current_api_key，供路由层注入使用

主要函数：
- verify_api_key(raw: str | None, expected: str) -> bool: 校验 Key 是否匹配
- get_current_api_key(x_api_key: str = Header(None)) -> str: FastAPI 依赖，失败抛 401
- decode_jwt(token: str) -> dict | None: （进阶）JWT 解码，返回 payload

关联方案：docs/design.md §2（core/security.py）、§8（配置与安全）。
"""
from fastapi import Header, HTTPException, status
import hmac


def verify_api_key(raw: str | None, expected: str) -> bool:
    ...


async def get_current_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    ...
