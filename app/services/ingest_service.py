"""业务·摄取原语 — 单个文件「怎么进 / 怎么出」索引（功能需求 FR1）。

**本模块在一期已降级为「原语层」**：不承担 vault 级编排（对账、护栏、dry_run、进度、取消），
那些全部上移到 `sync_service`（对账层）与 `run_service`（作业层）。

三层职责（不可越界，见 M03 §5.6）：
    作业层 run_service      何时跑、跑到哪了、能不能停
    对账层 sync_service     要动哪些文件、允不允许删
    原语层 ingest_service   单个文件怎么进 / 出索引     ← 本模块

文件级原语（供 sync_service 与 doctor 复用）：
- index_file：解析 → 分块 → 嵌入 → 写向量 + 元数据（文件级替换，先算后改）
- drop_file：删该文件的 chunks 行与对应向量
- move_file：仅改路径元数据（零 embedding）

所有原语在后台协程中运行，通过 session_scope 自取 DB 会话，不依赖请求作用域。

关联方案：M03 §4.1 / §5.6 / ADR-8；docs/design.md §16（多格式）、§18（多模型）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.core.database import session_scope
from app.models import Vault
from app.models.schemas import ModelRuntime
# 导入 app.parsers.base 会先执行 app/parsers/__init__，触发解析器自注册
from app.parsers.base import parse_file
from app.rag.chunker import Chunk as ChunkData
from app.rag.embedder import embed
from app.rag.vectorstore import VectorStore
from app.repositories import note_repo
from app.services import image_service
from app.services.model_service import collection_name

# 扩展名 → chunker 格式（决定是否按标题切分）
# .docx / .pdf 也走 markdown：解析器输出的就是 markdown 语法（标题 / 页码 → # 前缀），
# 走 markdown 模式才能按小节切分并生成面包屑
_FMT_BY_EXT = {
    ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html",
    ".docx": "markdown", ".pdf": "markdown",
}

# .env 种子运行时（无 ModelProfile 行）在集合命名中的 profile 占位
ENV_PROFILE_PLACEHOLDER = "env"


def _chunk_format(suffix: str) -> str:
    return _FMT_BY_EXT.get(suffix.lower(), "text")


# 正文里的图片语法 ![alt](target)：图片处理成功时会被替换成 IMAGE_START/END 描述块，
# 所以「只剩图片语法、没有任何文字」的 chunk 说明图片没被处理（未配置多模态 / 处理失败 / 图不可用）
_IMAGE_SYNTAX_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _is_image_shell(chunk: ChunkData) -> bool:
    """该 chunk 是否「只剩图片语法」—— 剥掉面包屑前缀与图片语法后没有任何实质文字。

    专治扫描件 PDF：未配置多模态 LLM 时每页的正文就剩 `![图片](pdf-image:N)`，
    这种 chunk 若入库，检索会召回一堆无信息量的命中。
    """
    text = chunk.text
    breadcrumb = chunk.metadata.get("breadcrumb")
    if breadcrumb:
        # chunker 把面包屑作为上下文前缀写进了正文（见 rag/chunker.py split_markdown）
        text = text.removeprefix(f"[{breadcrumb}]\n")
    return not _IMAGE_SYNTAX_RE.sub("", text).strip()


def _resolve_profile_id(vault: Vault, embed_profile_id: int | str | None) -> int | str:
    """确定本次写入的 embedding profile 标识：显式传入 > vault 当前绑定 > env 占位。"""
    if embed_profile_id is not None:
        return embed_profile_id
    if vault.embed_profile_id is not None:
        return vault.embed_profile_id
    return ENV_PROFILE_PLACEHOLDER


def _get_store(vault: Vault, profile_id: int | str) -> VectorStore:
    return VectorStore(
        persist_dir=settings.chroma_dir,
        collection_name=collection_name(vault.id, profile_id),
    )


async def index_file(
    vault: Vault,
    local_path: Path,
    rel_path: str,
    embed_runtime: ModelRuntime | None = None,
    embed_profile_id: int | str | None = None,
    max_chars: int = 800,
    image_runtime: ModelRuntime | None = None,
) -> int:
    """索引单个文件，返回分块数。实现 = 文件级替换（先算后改，再清旧写新）。

    顺序刻意「先计算、后变更」：解析/分块/嵌入成功前不动任何旧数据，
    避免一次失败的重索引把原有可检索内容删掉（M03 ADR-8）。

    image_runtime 为支持图片输入的多模态 LLM 时，分块后逐 chunk 把图片转成文字回插正文，
    并把图片溯源信息（uid / 图片地址 / 原始语法 / 偏移）写进 chunk.metadata["images"]，
    随向量 metadata 一起落到 Chroma；否则（None / 非多模态）跳过图片处理，仅按原文入库。
    """
    if embed_runtime is None:
        raise ValueError("index_file 需要 embed_runtime")

    stat = local_path.stat()
    content_hash = await asyncio.to_thread(file_content_hash, local_path)

    # 1) 解析（不支持的格式 / 空内容 → 跳过，返回 0，不动旧数据）
    doc = await asyncio.to_thread(parse_file, local_path)
    if doc is None:
        logger.warning("无可用解析器，跳过", vault_id=vault.id, path=rel_path)
        return 0

    # 1.5) 分块：对**原始内容**切分。图片处理必须放在切分之后 —— 若先替换整篇再切分，
    # 「哪个 chunk 含哪张图」的位置信息在切分前就永久丢失（见 image_service.attach_images）
    chunks: list[ChunkData] = doc.to_chunks(
        fmt=_chunk_format(local_path.suffix),
        max_chars=max_chars,
    )
    if not chunks:
        logger.info("文件无有效内容，跳过", vault_id=vault.id, path=rel_path)
        return 0

    # 1.6) 图片处理：逐 chunk 回插描述，并把溯源信息写进 chunk.metadata["images"]
    # （未启用多模态时直接返回，chunk 保持原样）
    await image_service.attach_images(
        chunks, doc.images, local_path, rel_path, vault, image_runtime
    )

    # 1.7) 丢弃空壳 chunk：图片没被处理时，纯图片段（如扫描件 PDF 的整页图）会剩下一段
    # 剥掉标记后没有任何文字的正文，入库只会污染检索结果。必须在图片处理**之后**判断 ——
    # 处理成功时标记已被替换成文字描述，就不会被判为空壳。
    chunks = [chunk for chunk in chunks if not _is_image_shell(chunk)]
    if not chunks:
        logger.info("图片处理后可检索内容为空，跳过", vault_id=vault.id, path=rel_path)
        return 0

    # 2) 嵌入（最易失败的一步，放在任何写操作之前）
    vectors = await embed([c.text for c in chunks], embed_runtime)
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"嵌入数量不匹配：chunks={len(chunks)} vectors={len(vectors)}"
        )

    profile_id = _resolve_profile_id(vault, embed_profile_id)
    store = _get_store(vault, profile_id)
    profile_id_int = profile_id if isinstance(profile_id, int) else None

    async with session_scope() as session:
        # 3) 清旧：取旧 vector_id（文件级替换，文件变短也不留幽灵向量）
        old_note = await note_repo.get_note_by_path(session, vault.id, rel_path)
        old_vector_ids: list[str] = []
        if old_note is not None:
            old_vector_ids = await note_repo.delete_chunks_by_note(session, old_note.id)

        # 4) notes 行（复用旧 note_id，保持同路径稳定）
        note = await note_repo.upsert_note(
            session,
            vault_id=vault.id,
            rel_path=rel_path,
            title=doc.title,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            content_hash=content_hash,
            user_id=vault.user_id,
        )

        # 5) 组装向量负载与 chunks 行数据（纯数据，ORM 构造在 note_repo 内）
        vector_ids: list[str] = []
        metadatas: list[dict] = []
        docs: list[str] = []
        rows: list[note_repo.ChunkRecord] = []
        for idx, ch in enumerate(chunks):
            vid = f"v{vault.id}_n{note.id}_c{idx}"
            vector_ids.append(vid)

            meta = {
                "vault_id": vault.id,
                "user_id": vault.user_id,
                "note_id": note.id,
                "source_file": rel_path,
                "title": doc.title,
                "chunk_index": idx,
            }
            # parser/splitter 元数据并入（Chroma 只接受基本类型）
            meta.update(_flatten_meta(ch.metadata))
            metadatas.append(meta)
            docs.append(ch.text)

            rows.append(
                note_repo.ChunkRecord(
                    vault_id=vault.id,
                    user_id=vault.user_id,
                    idx=idx,
                    content=ch.text,
                    char_start=int(ch.metadata.get("char_start", 0)),
                    char_end=int(ch.metadata.get("char_end", 0)),
                    vector_id=vid,
                    embed_profile_id=profile_id_int,
                )
            )

        # 6) 写向量库 + 删旧向量 + 写 chunks 行
        await store.add(vector_ids, vectors, docs, metadatas)
        if old_vector_ids:
            # 旧向量可能含「本次不再存在」的 id；新 vid 与旧 vid 同规则，重复删无害
            stale = [v for v in old_vector_ids if v not in set(vector_ids)]
            if stale:
                await store.delete(stale)
        await note_repo.replace_chunks(session, note.id, rows)

    logger.info(
        "index_file 完成",
        vault_id=vault.id, path=rel_path, chunks=len(chunks),
        collection=collection_name(vault.id, profile_id),
    )
    return len(chunks)


async def drop_file(vault: Vault, note_id: int) -> None:
    """删除某文件的 chunks 行与对应向量（文件删除 / 移出过滤范围时用）。"""
    profile_id = _resolve_profile_id(vault, None)
    store = _get_store(vault, profile_id)

    async with session_scope() as session:
        vector_ids = await note_repo.delete_chunks_by_note(session, note_id)
        if vector_ids:
            await store.delete(vector_ids)
        await note_repo.delete_note_cascade(session, note_id)

    logger.info("drop_file 完成", vault_id=vault.id, note_id=note_id, chunks=len(vector_ids))


async def move_file(vault: Vault, note_id: int, new_rel_path: str) -> None:
    """内容未变、仅路径变化：只更新 notes.file_path 与 Chroma metadata。零 embedding。"""
    profile_id = _resolve_profile_id(vault, None)
    store = _get_store(vault, profile_id)

    async with session_scope() as session:
        vector_ids = await note_repo.list_vector_ids_by_note(session, note_id)
        await note_repo.update_note_path(session, note_id, new_rel_path)

    if vector_ids:
        metadatas = await store.get_metadatas(vector_ids)
        updated = []
        for meta in metadatas:
            if meta is None:
                continue
            meta = dict(meta)
            meta["source_file"] = new_rel_path
            updated.append(meta)
        # metadatas 与 ids 顺序对应；仅更新取到的（None 项理论上不应出现）
        valid_ids = vector_ids[: len(updated)]
        if updated:
            await store.update_metadata(valid_ids, updated)

    logger.info("move_file 完成", vault_id=vault.id, note_id=note_id, new_path=new_rel_path)


# ===== 内部工具 =====


def _flatten_meta(meta: dict) -> dict:
    """把 splitter/parser 元数据规整为 Chroma 兼容的基本类型（list/dict → JSON 字符串）。"""
    flat: dict = {}
    for k, v in (meta or {}).items():
        if v is None or isinstance(v, (str, int, float, bool)):
            flat[k] = v
        else:
            flat[k] = json.dumps(v, ensure_ascii=False)
    return flat


def file_content_hash(path: Path) -> str:
    """内容哈希：sha256(文件字节) 前 16 位 hex（变更判据 L2）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()[:16]
