"""数据访问·图片缓存 — image_cache 表的 CRUD。

能力：
- 按内容寻址读取 / 写入图片处理结果（本地图 sha256(字节)、远程图 sha256(url)）
- 多用户模式按 user_id 隔离，避免不同用户对同一图片的结果串号
- 维护 uid（chunk 的 metadata["images"][].uid 据它关联到本行）

主要函数：
- make_uid(user_id, content_key) -> str：缓存行的稳定短标识
- async def get_cached(session, user_id, content_key) -> ImageCache | None（命中时懒补 uid）
- async def upsert_cached(session, user_id, ..., source_ref) -> None
- delete: 无 —— 图片缓存与 vault 无关（内容寻址，可跨 vault 复用）

关键约定：
- 本模块只碰 SQLite；多模态模型调用在 service 层
- **不记 chunk_id**：一张图可被多个 chunk / 文档引用，而 chunk 行每次索引整体
  删后重建（主键会变），绑上去必然失效。chunk 侧的溯源由 metadata["images"] 承担

关联方案：图片处理方案（image-progress 约定）。
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImageCache


def make_uid(user_id: str, content_key: str) -> str:
    """图片缓存行的稳定短标识：img_ + sha256(user_id:content_key) 前 16 位。

    必须把 user_id 掺进哈希：唯一键是 (user_id, content_key)，若只取 content_key
    的前缀，两个用户引用同一张图会算出同一个 uid 而撞上唯一索引。
    """
    raw = f"{user_id}:{content_key}".encode("utf-8")
    return "img_" + hashlib.sha256(raw).hexdigest()[:16]


async def get_cached(session: AsyncSession, user_id: str, content_key: str) -> ImageCache | None:
    """按 (user_id, content_key) 取缓存行，未命中返回 None。

    老库的存量行没有 uid（补列时只能落 NULL），命中时顺手补上并提交 ——
    否则 chunk 的 metadata 里拿不到关联依据，溯源链就断了。
    """
    result = await session.execute(
        select(ImageCache).where(
            ImageCache.user_id == user_id,
            ImageCache.content_key == content_key,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None and not row.uid:
        row.uid = make_uid(user_id, content_key)
        await session.commit()
    return row


async def upsert_cached(
    session: AsyncSession,
    user_id: str,
    source_kind: str,
    content_key: str,
    content: str,
    model: str = "",
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
    processor: str = "llm-vision",
    source_ref: str = "",
) -> None:
    """写入 / 更新一条图片处理缓存（按 (user_id, content_key) 去重）。

    source_ref 为图片地址（远程 URL / 本地相对 vault 根的路径）：同一张图可能从
    不同 vault 以不同路径引用，这里记的是**最近一次**。
    """
    uid = make_uid(user_id, content_key)
    existing = await get_cached(session, user_id, content_key)
    if existing is not None:
        existing.uid = uid
        existing.source_kind = source_kind
        existing.source_ref = source_ref or existing.source_ref
        existing.processor = processor
        existing.content = content
        existing.model = model
        existing.width = width
        existing.height = height
        existing.size_bytes = size_bytes
    else:
        session.add(
            ImageCache(
                user_id=user_id,
                uid=uid,
                source_kind=source_kind,
                source_ref=source_ref,
                content_key=content_key,
                processor=processor,
                content=content,
                model=model,
                width=width,
                height=height,
                size_bytes=size_bytes,
            )
        )
    await session.commit()
