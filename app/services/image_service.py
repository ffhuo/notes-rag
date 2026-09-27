"""业务·图片处理 — 把笔记里的图片转成可检索的文字，回插正文后再分块。

设计要点（与 image-progress 方案一致）：
- **是否处理图片不由开关决定**：仅当传入的 LLM 运行时 `params.multimodal` 为真时才处理。
  没有多模态 LLM 时整段跳过（INFO 日志），**绝不让文件索引失败** —— 与 chat 接口缺配置
  返回 409 的语义刻意不同：图片只是增强，缺配置不该阻断入库。
- **远程 http/https 外链：不下载**，直接把原始 URL 作为 image_url 交给模型。由此：
  远程图跳过尺寸校验、缓存键只能是 sha256(url)（URL 不变而内容变化不被感知）。
- **本地图**：读字节 → Pillow 校验宽高 / 格式 → base64 Data URL；路径限制在 vault 根内，
  防止 `![x](/etc/passwd)` 之类的越权读取把本机文件送上云端。
- 处理发生在**切分之后**：在已切分的 chunk 上按 ref.raw 定位图片语法、就地替换为
  `<!-- IMAGE_START -->…<!-- IMAGE_END -->`，并把「本片含哪张图」写进
  chunk.metadata["images"]（uid / ref / raw / alt / offset / model），供检索展示与
  溯源验证。若改成「先替换整篇再切分」，图片位置信息会在切分前永久丢失，故不倒过来做。
- 模型返回 EMPTY / 任何失败一律降级为「保留原图片语法」，不阻塞该文件其余内容。
- 处理结果按内容寻址缓存到 image_cache 表（本地 sha256(字节)、远程 sha256(url)），
  避免同一图片跨文档 / 跨作业重复调用多模态模型；缓存行另带 uid 与图片地址
  source_ref，chunk 侧凭 uid 关联回该行。

主要函数：
- is_supported(runtime) -> bool：该 LLM 运行时是否支持图片输入
- async def attach_images(chunks, refs, local_path, rel_path, vault, image_runtime) -> None：
  就地回插图片描述 + 写 chunk.metadata["images"]（无返回值）

关联方案：image-progress 图片方案；docs/design.md §16（多格式解析）、§18（多模型管理）。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from loguru import logger
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_scope
from app.models import Vault
from app.models.schemas import ModelRuntime
from app.parsers.base import ImageRef
from app.rag.chunker import Chunk
from app.rag.llm_client import chat
from app.repositories import image_repo

# 回插标记：替换后的正文里，图片描述被这对注释包裹，便于人工排查与后续二次处理
IMAGE_MARKER_START = "<!-- IMAGE_START -->"
IMAGE_MARKER_END = "<!-- IMAGE_END -->"

# 模型明确表示「图片无信息价值」时的回复（据此保留原图片语法）
_EMPTY_TOKEN = "EMPTY"

_REMOTE_PREFIXES = ("http://", "https://")

# Obsidian 常见附件目录：wikilink 只给裸文件名时按此顺序兜底查找
_WIKI_ATTACH_DIRS = ("attachments", "assets", "images", "img", "media", "files")

# PIL format → MIME（Data URL 用）；未知格式再按扩展名兜底
_MIME_BY_PIL = {
    "PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif",
    "WEBP": "image/webp", "BMP": "image/bmp", "TIFF": "image/tiff",
}
_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}
_IMAGE_EXTS = tuple(_MIME_BY_EXT.keys())

_PROMPT = (
    "请阅读这张图片，只输出一段简洁的中文文字，不要任何解释、客套或 Markdown 代码块：\n"
    "1. 若图中有文字，按阅读顺序完整提取；\n"
    "2. 若图中有结构（流程图 / 表格 / 思维导图 / 架构图 / 示意图），用文字描述其结构与关系；\n"
    "3. 以上内容可同时给出；\n"
    "4. 若图片没有可读文字且没有明显信息价值（纯装饰、纯色块、无意义图标），只回复 EMPTY。"
)


@dataclass
class _Prepared:
    """一张图片的取数据结果（ok=False 时 reason 说明降级原因）。"""

    ok: bool
    source_kind: str = ""
    source_ref: str = ""       # 图片地址：远程=完整 URL；本地=相对 vault 根的 POSIX 路径
    content_key: str = ""
    payload_url: str = ""      # 交给模型的 image_url（远程原始 URL 或本地 Data URL）
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    reason: str = ""


def is_supported(runtime: ModelRuntime | None) -> bool:
    """该 LLM 运行时是否支持图片输入（唯一判据：params.multimodal 为真）。"""
    return bool(
        runtime is not None
        and runtime.kind == "llm"
        and runtime.params.get("multimodal")
    )


def _is_remote(target: str) -> bool:
    return target.lower().startswith(_REMOTE_PREFIXES)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vault_root_of(local_path: Path, rel_path: str) -> Path:
    """由「文件绝对路径 + 相对 vault 根的相对路径」反推 vault 根目录。"""
    root = local_path
    for _ in Path(rel_path.replace("\\", "/")).parts:
        root = root.parent
    return root


def _resolve_local(target: str, md_dir: Path, vault_root: Path, kind: str) -> Path | None:
    """把图片目标解析为磁盘路径；限制在 vault 根内，越界返回 None。

    查找顺序：md 所在目录 → vault 根 → vault 根下的常见附件目录（仅 wikilink 裸名时）。
    目标缺失扩展名时补常见图片扩展名再试；含 %20 等编码时同时试原始与解码后的名字。
    """
    targets = [target]
    if "%" in target:
        decoded = unquote(target)
        if decoded != target:
            targets.append(decoded)

    def _variants(base: Path, raw: str) -> list[Path]:
        p = base / raw
        out = [p]
        if not p.suffix:
            out += [p.with_suffix(ext) for ext in _IMAGE_EXTS]
        return out

    bases: list[Path] = [md_dir]
    if kind == "wiki":
        bases += [vault_root] + [vault_root / sub for sub in _WIKI_ATTACH_DIRS]

    root_resolved = vault_root.resolve()
    for base in bases:
        for raw in targets:
            for cand in _variants(base, raw):
                try:
                    resolved = cand.resolve()
                except OSError:
                    continue
                # 越界防护：解析后必须仍在 vault 根内
                if resolved != root_resolved and root_resolved not in resolved.parents:
                    continue
                if resolved.is_file():
                    return resolved
    return None


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]*)(?P<base64>;base64)?,(?P<payload>.*)$", re.DOTALL)


def _decode_data_url(url: str) -> bytes | None:
    """把 data: URL 解回原始字节；只认 base64 载荷（percent-encoded 视为不可处理）。

    返回 None 表示拿不到可用字节，调用方按「保留原图片语法」处理。
    """
    match = _DATA_URL_RE.match(url)
    if match is None or not match.group("base64"):
        return None
    try:
        return base64.b64decode(match.group("payload"), validate=False)
    except Exception:  # noqa: BLE001 —— 坏 base64 一律降级
        return None


def _measure_image(data: bytes, suffix: str = "") -> tuple[bytes, str, int, int] | None:
    """校验图片字节并测量，返回 (字节, mime, 宽, 高)；不合格返回 None。

    本地图与内嵌图（data: URL，如 Word 内嵌图片）**共用同一套阈值** —— 两类都是有真实
    字节的图片，标准必须一致；否则 Word 里的 logo / 项目符号小图标会白白占用多模态调用。
    远程外链不下载、不走此校验（见 _prepare_remote）。
    只读文件头即可拿到尺寸 / 格式，不做完整解码。
    """
    try:
        if not data or len(data) > settings.image_max_bytes:
            return None
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
        mime = _MIME_BY_PIL.get(fmt) or _MIME_BY_EXT.get(suffix)
        if mime is None:
            return None
        if width < settings.image_min_width or height < settings.image_min_height:
            return None
        return data, mime, width, height
    except Exception:  # noqa: BLE001 —— 任何解码异常都降级为「忽略该图」
        return None


def _read_local_image(path: Path) -> tuple[bytes, str, int, int] | None:
    """读取本地图字节并交给 _measure_image 校验；读不到 / 不合格返回 None。

    阻塞 IO + Pillow 解码，调用方应放入线程池。
    """
    try:
        if not path.is_file():
            return None
        # 先看文件大小，避免把超大文件整个读进内存
        size = path.stat().st_size
        if size <= 0 or size > settings.image_max_bytes:
            return None
        return _measure_image(path.read_bytes(), path.suffix.lower())
    except Exception:  # noqa: BLE001 —— 任何读取异常都降级为「忽略该图」
        return None


def _prepare_remote(target: str) -> _Prepared:
    """远程外链：不下载、不校验尺寸，直接用原始 URL 交给模型。"""
    return _Prepared(
        ok=True, source_kind="remote",
        source_ref=target,
        content_key=_sha256_hex(target.encode("utf-8")),
        payload_url=target,
    )


async def prepare(ref: ImageRef, md_dir: Path, vault_root: Path) -> _Prepared:
    """准备一张图片：远程直传 URL；本地读字节做尺寸校验后转 Data URL。

    source_ref 记「图片地址」：远程=完整 URL；本地=相对 vault 根的 POSIX 路径
    （与 notes.file_path 同规范，便于前端回填时按 vault 定位）。
    """
    target = ref.target.strip()
    if not target:
        return _Prepared(ok=False, reason="empty_target")
    # data: URL（Word 内嵌图、markdown 里的 base64 内联图）：字节已在手上，不落盘也不读盘。
    # 与本地图走同一套校验（_measure_image）——否则 Word 里的 logo / 小图标会白占调用额度；
    # content_key 取 sha256(原始字节)，与本地图同规范（同一张图两种来源可共享缓存）；
    # source_kind 记 embedded：它不是远程外链，标成 remote 会误导溯源。
    # 内嵌图没有可供回填的外部地址，source_ref 留空。
    if target.lower().startswith("data:"):
        data = _decode_data_url(target)
        measured = _measure_image(data) if data else None
        if measured is None:
            return _Prepared(ok=False, reason="invalid_data_url")
        raw, mime, width, height = measured
        b64 = base64.b64encode(raw).decode("ascii")
        return _Prepared(
            ok=True, source_kind="embedded",
            content_key=_sha256_hex(raw),
            payload_url=f"data:{mime};base64,{b64}",
            width=width, height=height, size_bytes=len(raw),
        )
    if _is_remote(target):
        return _prepare_remote(target)

    path = await asyncio.to_thread(_resolve_local, target, md_dir, vault_root, ref.kind)
    if path is None:
        return _Prepared(ok=False, reason="not_found")
    loaded = await asyncio.to_thread(_read_local_image, path)
    if loaded is None:
        return _Prepared(ok=False, reason="invalid_or_too_small")
    data, mime, width, height = loaded
    try:
        source_ref = path.relative_to(vault_root.resolve()).as_posix()
    except ValueError:          # 防御：_resolve_local 已保证在 vault 根内，理论不可达
        source_ref = ""
    b64 = base64.b64encode(data).decode("ascii")
    return _Prepared(
        ok=True, source_kind="local",
        source_ref=source_ref,
        content_key=_sha256_hex(data),
        payload_url=f"data:{mime};base64,{b64}",
        width=width, height=height, size_bytes=len(data),
    )


async def understand(prepared: _Prepared, image_runtime: ModelRuntime) -> str:
    """调用多模态 LLM 理解单张图片，返回文字；模型认为无价值时返回空串。"""
    vision_runtime = image_runtime.model_copy(
        update={"params": {**image_runtime.params, "temperature": 0.1}}
    )
    messages = [
        {"role": "system", "content": "你是严谨的文档图片理解助手。"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": prepared.payload_url}},
            ],
        },
    ]
    text = (await chat(messages, vision_runtime)).strip()
    if not text or text.upper().startswith(_EMPTY_TOKEN):
        return ""
    return text


async def attach_images(
    chunks: list[Chunk],
    refs: list[ImageRef],
    local_path: Path,
    rel_path: str,
    vault: Vault,
    image_runtime: ModelRuntime | None,
) -> None:
    """把图片转成文字回插到**各个 chunk**，并写 chunk.metadata["images"]。

    就地修改 chunks（text 与 metadata），无返回值。无图 / 未启用多模态时直接返回。
    单独一张图失败只降级为「保留原语法」，绝不影响该文件其余内容入库。
    """
    if not chunks or not refs:
        return
    if not is_supported(image_runtime):
        logger.info(
            "未配置多模态 LLM，跳过图片处理",
            vault_id=vault.id, path=rel_path, images=len(refs),
        )
        return

    if len(refs) > settings.image_max_per_doc:
        logger.info(
            "图片数超出上限，其余忽略",
            vault_id=vault.id, path=rel_path,
            total=len(refs), limit=settings.image_max_per_doc,
        )
        refs = refs[: settings.image_max_per_doc]

    md_dir = local_path.parent
    vault_root = _vault_root_of(local_path, rel_path)
    async with session_scope() as session:
        for chunk in chunks:
            await _attach_to_chunk(
                chunk, refs, md_dir, vault_root, vault, image_runtime, session, rel_path
            )


async def _attach_to_chunk(
    chunk: Chunk,
    refs: list[ImageRef],
    md_dir: Path,
    vault_root: Path,
    vault: Vault,
    image_runtime: ModelRuntime,
    session: AsyncSession,
    rel_path: str,
) -> None:
    """处理单个 chunk 内的图片：替换正文片段 + 写 metadata["images"]。

    用 ref.raw 在 chunk.text 里查找，而不依赖 char_start：切分的 overlap 会让偏移
    成为近似值，按原文片段查找更可靠。找不到 = 图片语法被切分边界截断，跳过并保留
    残缺原文（模块 docstring 已说明该取舍）。同一张图若因 overlap 落入相邻两片，
    两片都会记录它 —— 符合「本片确实含这张图」的事实。
    """
    hits: list[tuple[int, ImageRef]] = []
    for ref in refs:
        pos = chunk.text.find(ref.raw)
        if pos >= 0:
            hits.append((pos, ref))
    if not hits:
        return
    hits.sort(key=lambda item: item[0])

    text = chunk.text
    records: list[dict] = []
    # 从后往前替换：先动靠后的位置，前面命中的下标才不会失效
    for pos, ref in reversed(hits):
        prepared = await prepare(ref, md_dir, vault_root)
        if not prepared.ok:
            logger.info(
                "图片不可用，保留原语法",
                vault_id=vault.id, path=rel_path, target=ref.target, reason=prepared.reason,
            )
            continue

        cached = await image_repo.get_cached(session, vault.user_id, prepared.content_key)
        if cached is not None and cached.content:
            # 缓存命中：直接复用，省一次模型调用
            desc = cached.content
            uid = cached.uid or image_repo.make_uid(vault.user_id, prepared.content_key)
            model = cached.model
            if prepared.source_ref and not cached.source_ref:
                # 老数据缺地址：用本次解析结果补上，便于后续回填
                cached.source_ref = prepared.source_ref
                await session.commit()
        else:
            try:
                desc = await understand(prepared, image_runtime)
            except Exception as e:  # noqa: BLE001 —— 上游抖动不能让整篇入库失败
                logger.warning(
                    "图片理解失败，保留原语法",
                    vault_id=vault.id, path=rel_path, target=ref.target, error=str(e),
                )
                continue
            if not desc:
                # 模型判定无信息价值：保留原图片语法，且不写缓存（避免把「无价值」固化）
                continue
            uid = image_repo.make_uid(vault.user_id, prepared.content_key)
            model = image_runtime.model
            # 成功结果才写缓存（失败 / EMPTY 不写，留待下次重试）
            await image_repo.upsert_cached(
                session,
                user_id=vault.user_id,
                source_kind=prepared.source_kind,
                content_key=prepared.content_key,
                content=desc,
                model=model,
                width=prepared.width,
                height=prepared.height,
                size_bytes=prepared.size_bytes,
                source_ref=prepared.source_ref,
            )

        text = text[:pos] + _wrap(desc) + text[pos + len(ref.raw):]
        records.append(
            {
                "uid": uid,                     # 关联 image_cache 行（溯源依据）
                "ref": prepared.source_ref,     # 图片地址：url 或 path
                "kind": prepared.source_kind,   # local | remote
                "raw": ref.raw,                 # 原始图片语法，供回填
                "alt": ref.alt,
                "offset": pos,                  # 在 chunk.text 内的字符偏移
                "model": model,
            }
        )

    if not records:
        return
    records.sort(key=lambda item: item["offset"])
    chunk.text = text
    chunk.metadata["images"] = records


def _wrap(text: str) -> str:
    return f"{IMAGE_MARKER_START}\n{text}\n{IMAGE_MARKER_END}"
