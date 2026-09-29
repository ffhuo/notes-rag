"""图片处理测试 — 覆盖三类语法、路径解析、缓存命中、溯源元数据与各种降级路径。

关键设计断言：
- 唯一开关是 LLM 的 params.multimodal（没有 image_enabled 这类字段）
- 远程 http/https 外链不下载、直接传 URL，且跳过尺寸校验
- 本地图读字节 → 尺寸校验 → base64 Data URL；越界路径被拒绝
- 模型返回 EMPTY / 上游失败 / 图不可用 → 保留原图片语法，不阻塞入库
- 处理结果按内容寻址缓存，第二次同图不再调用模型
- **处理发生在切分之后**：图片信息写进**所在 chunk** 的 metadata["images"]，
  含 uid（关联 image_cache 行）/ ref（图片地址：URL 或相对 vault 根的路径）/
  raw（原语法，供回填）/ offset（本片内偏移）
- 「哪个 LLM 支持图片输入」由 resolve_image_runtime 解析（默认项优先，无则任一启用的多模态 LLM）

关联方案：图片处理方案；docs/design.md §9.1（测试与质量）。
"""
import base64
import hashlib
import json

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from app.core import database
from app.core.config import settings
from app.models import ImageCache, ModelProfile, Vault
from app.models.schemas import ModelRuntime
from app.parsers.markdown import MarkdownParser
from app.rag.chunker import Chunk
from app.repositories import model_repo
from app.services import image_service, model_service


# ===== 夹具 =====


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """临时 SQLite：建表 → 用例 → 关闭引擎（避免全局引擎在用例间串库）。"""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


@pytest.fixture
def vault():
    return Vault(id=1, user_id="default", name="v", source_type="local", source_value="/tmp/v")


def _runtime(multimodal: bool = True) -> ModelRuntime:
    params = {"multimodal": True} if multimodal else {}
    return ModelRuntime(
        kind="llm", name="vlm", base_url="", api_key=SecretStr("k"),
        model="qwen-vl", params=params,
    )


def _png(path, size=(400, 300)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path)


def _write_md(tmp_path, text: str):
    md = tmp_path / "note.md"
    md.write_text(text, encoding="utf-8")
    return md


def _capture_chat(monkeypatch, reply="图中有文字「架构」"):
    """替换 image_service.chat，记录每次调用传入的消息。"""
    calls: list[list[dict]] = []

    async def fake_chat(messages, runtime, **kwargs):
        calls.append(messages)
        return reply

    monkeypatch.setattr(image_service, "chat", fake_chat)
    return calls


def _image_url_of(messages) -> str:
    # messages = [system, user]，图片在 user 消息的内容块里
    content = messages[1]["content"]
    part = next(p for p in content if p["type"] == "image_url")
    return part["image_url"]["url"]


async def _attach(doc, md, rel_path, vault, runtime, max_chars: int = 1000) -> list[Chunk]:
    """按 ingest 的真实顺序（先切分、再处理图片）产出 chunks 并就地回插。"""
    chunks = doc.to_chunks(fmt="markdown", max_chars=max_chars)
    await image_service.attach_images(chunks, doc.images, md, rel_path, vault, runtime)
    return chunks


def _text_of(chunks) -> str:
    return "".join(c.text for c in chunks)


def _images_of(chunks) -> list[dict]:
    """汇总所有 chunk 的图片记录（每条记录都归属于它所在的那一片）。"""
    out: list[dict] = []
    for c in chunks:
        out.extend(c.metadata.get("images", []))
    return out


async def _cache_rows() -> list[ImageCache]:
    async with database.session_scope() as session:
        result = await session.execute(select(ImageCache))
        return list(result.scalars().all())


# ===== 开关判定 =====


def test_is_supported_only_multimodal():
    assert image_service.is_supported(_runtime(True)) is True
    assert image_service.is_supported(_runtime(False)) is False
    assert image_service.is_supported(None) is False
    # kind 不是 llm 的一律不支持
    embed = ModelRuntime(kind="embed", name="e", base_url="", api_key=SecretStr(""), model="m", params={"multimodal": True})
    assert image_service.is_supported(embed) is False


@pytest.mark.asyncio
async def test_skip_when_not_multimodal(tmp_path):
    """没有多模态 LLM 时整段跳过：正文原样，不写溯源信息。"""
    md = _write_md(tmp_path, "正文 ![图](img/a.png) 结束")
    doc = MarkdownParser().parse(md)
    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime(False))

    assert _text_of(chunks) == doc.content
    assert _images_of(chunks) == []


# ===== 远程外链：不下载、直传 =====


@pytest.mark.asyncio
async def test_remote_url_passed_directly(db, tmp_path, monkeypatch):
    url = "https://cdn.example.com/a.png"
    md = _write_md(tmp_path, f"看图 ![外链]({url}) 完")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())
    out = _text_of(chunks)

    # 原 URL 原样交给模型（未下载、未转 base64）
    assert _image_url_of(calls[0]) == url
    assert image_service.IMAGE_MARKER_START in out
    assert "架构" in out
    # 原图片语法已被替换
    assert f"![外链]({url})" not in out

    # 溯源：本片记录了图片地址（url）、种类、原语法与本片内偏移
    rec = _images_of(chunks)[0]
    assert rec["kind"] == "remote"
    assert rec["ref"] == url
    assert rec["raw"] == f"![外链]({url})"
    assert rec["offset"] == out.index(image_service.IMAGE_MARKER_START)
    # uid 是 chunk → image_cache 行的关联依据
    rows = await _cache_rows()
    assert [r.uid for r in rows] == [rec["uid"]]


# ===== 本地图：路径解析 + Data URL + 相对路径回填信息 =====


@pytest.mark.asyncio
async def test_local_image_data_url(db, tmp_path, monkeypatch):
    vault_root = tmp_path
    _png(vault_root / "img" / "pic.png")
    md = _write_md(vault_root, "![本地](img/pic.png)")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    url = _image_url_of(calls[0])
    assert url.startswith("data:image/png;base64,")
    # 解码回来仍是一张合法 PNG
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    # 本地图地址记相对 vault 根的 POSIX 路径（与 notes.file_path 同规范）
    rec = _images_of(chunks)[0]
    assert rec["kind"] == "local"
    assert rec["ref"] == "img/pic.png"
    rows = await _cache_rows()
    assert rows[0].source_ref == "img/pic.png"


@pytest.mark.asyncio
async def test_wikilink_bare_name_resolved_in_attachment_dir(db, tmp_path, monkeypatch):
    """Obsidian wikilink 裸文件名 → 在 vault 根的 attachments 目录下找到。"""
    vault_root = tmp_path / "vault"
    _png(vault_root / "attachments" / "diagram.png")
    md = vault_root / "sub" / "note.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("![[diagram.png]]", encoding="utf-8")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "sub/note.md", Vault(id=1, user_id="default"), _runtime())
    out = _text_of(chunks)

    assert len(calls) == 1
    assert _image_url_of(calls[0]).startswith("data:image/png;base64,")
    assert "![[diagram.png]]" not in out
    # 地址是相对 vault 根（vault/sub/note.md 的根是 vault）
    assert _images_of(chunks)[0]["ref"] == "attachments/diagram.png"


@pytest.mark.asyncio
async def test_url_encoded_filename_resolved(db, tmp_path, monkeypatch):
    """带空格的本地图（Markdown 里编码为 %20）能被正确解析。"""
    _png(tmp_path / "img" / "my pic.png")
    md = _write_md(tmp_path, "![x](img/my%20pic.png)")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    assert len(calls) == 1
    assert _image_url_of(calls[0]).startswith("data:image/png;base64,")
    # 存的是**解码后**的真实磁盘相对路径，便于前端按 vault 回填
    assert _images_of(chunks)[0]["ref"] == "img/my pic.png"


@pytest.mark.asyncio
async def test_wikilink_without_extension_resolved(db, tmp_path, monkeypatch):
    """Obsidian wikilink 常省略扩展名 → 补常见图片扩展名后找到。"""
    vault_root = tmp_path / "vault"
    _png(vault_root / "assets" / "flow.png")
    md = vault_root / "note.md"
    md.write_text("![[flow]]", encoding="utf-8")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    assert len(calls) == 1
    assert _images_of(chunks)[0]["ref"] == "assets/flow.png"


@pytest.mark.asyncio
async def test_path_traversal_rejected(db, tmp_path, monkeypatch):
    """越出 vault 根的本地路径被拒绝，保留原语法，且不写溯源信息。"""
    vault_root = tmp_path / "vault"
    (vault_root / "sub").mkdir(parents=True)
    md = vault_root / "sub" / "note.md"
    md.write_text("![x](../../secret.png)", encoding="utf-8")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "sub/note.md", Vault(id=1, user_id="default"), _runtime())

    assert calls == []
    assert "![x](../../secret.png)" in _text_of(chunks)
    assert _images_of(chunks) == []
    assert await _cache_rows() == []


# ===== 降级路径 =====


@pytest.mark.asyncio
async def test_local_image_too_small_preserved(db, tmp_path, monkeypatch):
    """本地图小于阈值 → 忽略，保留原图片语法。"""
    _png(tmp_path / "small.png", size=(50, 50))
    md = _write_md(tmp_path, "![小图](small.png)")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    assert calls == []
    assert "![小图](small.png)" in _text_of(chunks)
    assert _images_of(chunks) == []


@pytest.mark.asyncio
async def test_missing_local_image_preserved(db, tmp_path, monkeypatch):
    md = _write_md(tmp_path, "![缺](img/nope.png)")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    assert calls == []
    assert "![缺](img/nope.png)" in _text_of(chunks)
    assert _images_of(chunks) == []


@pytest.mark.asyncio
async def test_empty_reply_preserves_original_and_not_cached(db, tmp_path, monkeypatch):
    """模型回 EMPTY → 保留原图片语法，且不写缓存（下次仍会重试）。"""
    url = "https://cdn.example.com/deco.png"
    md = _write_md(tmp_path, f"![装饰]({url})")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch, reply="EMPTY")

    vault = Vault(id=1, user_id="default")
    chunks = await _attach(doc, md, "note.md", vault, _runtime())
    out = _text_of(chunks)
    assert f"![装饰]({url})" in out
    assert image_service.IMAGE_MARKER_START not in out
    assert _images_of(chunks) == []
    assert await _cache_rows() == []

    # 未缓存：再跑一次仍会调用模型
    await _attach(doc, md, "note.md", vault, _runtime())
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_upstream_failure_degrades(db, tmp_path, monkeypatch):
    """上游 LLM 抛错 → 单图降级为保留原语法，不影响其余入库。"""
    url = "https://cdn.example.com/a.png"
    md = _write_md(tmp_path, f"前 ![图]({url}) 后")
    doc = MarkdownParser().parse(md)

    async def boom(messages, runtime, **kwargs):
        raise RuntimeError("503")

    monkeypatch.setattr(image_service, "chat", boom)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())
    out = _text_of(chunks)

    assert f"![图]({url})" in out
    assert out.startswith("前 ")
    assert _images_of(chunks) == []


# ===== 缓存命中 =====


@pytest.mark.asyncio
async def test_cache_hit_skips_second_call(db, tmp_path, monkeypatch):
    """同一远程 URL 第二次处理命中缓存，不再调用模型，且 uid 稳定。"""
    url = "https://cdn.example.com/same.png"
    md = _write_md(tmp_path, f"![图]({url})")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch, reply="缓存内容")
    vault = Vault(id=1, user_id="default")

    chunks1 = await _attach(doc, md, "note.md", vault, _runtime())
    chunks2 = await _attach(doc, md, "note.md", vault, _runtime())

    assert len(calls) == 1
    assert "缓存内容" in _text_of(chunks1) and "缓存内容" in _text_of(chunks2)
    # 两次引用同一张图 → 同一个 uid，指向同一行缓存
    assert _images_of(chunks1)[0]["uid"] == _images_of(chunks2)[0]["uid"]
    assert len(await _cache_rows()) == 1


@pytest.mark.asyncio
async def test_cache_isolated_per_user(db, tmp_path, monkeypatch):
    """不同用户对同一图片的处理结果互不复用（多用户防串号），uid 也互不相同。"""
    url = "https://cdn.example.com/same.png"
    md = _write_md(tmp_path, f"![图]({url})")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch, reply="结果")

    c1 = await _attach(doc, md, "note.md", Vault(id=1, user_id="u1"), _runtime())
    c2 = await _attach(doc, md, "note.md", Vault(id=2, user_id="u2"), _runtime())

    assert len(calls) == 2
    assert _images_of(c1)[0]["uid"] != _images_of(c2)[0]["uid"]


@pytest.mark.asyncio
async def test_legacy_row_without_uid_backfilled(db, tmp_path, monkeypatch):
    """老库存量行没有 uid / source_ref → 命中时懒补，溯源链不断。"""
    url = "https://cdn.example.com/legacy.png"
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    async with database.session_scope() as session:
        session.add(
            ImageCache(
                user_id="default", uid=None, source_kind="remote",
                source_ref="", content_key=key, content="老描述", model="old",
            )
        )

    md = _write_md(tmp_path, f"![图]({url})")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch)

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())

    assert calls == []                      # 命中缓存，不再调模型
    rec = _images_of(chunks)[0]
    assert rec["uid"]
    assert rec["ref"] == url                # 老行缺 source_ref，用本次解析结果补上
    rows = await _cache_rows()
    assert rows[0].uid == rec["uid"]
    assert rows[0].source_ref == url


# ===== 多图与上限 =====


@pytest.mark.asyncio
async def test_multiple_images_spliced_in_order(db, tmp_path, monkeypatch):
    url1, url2 = "https://cdn.example.com/1.png", "https://cdn.example.com/2.png"
    md = _write_md(tmp_path, f"A ![一]({url1}) B ![二]({url2}) C")
    doc = MarkdownParser().parse(md)
    _capture_chat(monkeypatch, reply="描述")

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())
    out = _text_of(chunks)

    assert out.count(image_service.IMAGE_MARKER_START) == 2
    assert out.startswith("A ") and out.endswith(" C")
    # 记录按出现顺序，偏移递增
    recs = _images_of(chunks)
    assert [r["ref"] for r in recs] == [url1, url2]
    assert recs[0]["offset"] < recs[1]["offset"]


@pytest.mark.asyncio
async def test_max_per_doc_limits_processing(db, tmp_path, monkeypatch):
    """超过单文档上限的图片被忽略，保留原语法。"""
    monkeypatch.setattr(settings, "image_max_per_doc", 1)
    url1, url2 = "https://cdn.example.com/1.png", "https://cdn.example.com/2.png"
    md = _write_md(tmp_path, f"![一]({url1}) ![二]({url2})")
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch, reply="描述")

    chunks = await _attach(doc, md, "note.md", Vault(id=1, user_id="default"), _runtime())
    out = _text_of(chunks)

    assert len(calls) == 1
    assert out.count(image_service.IMAGE_MARKER_START) == 1
    assert url2 in out
    assert len(_images_of(chunks)) == 1


# ===== 溯源：图片只归它所在的 chunk =====


@pytest.mark.asyncio
async def test_image_recorded_only_in_own_chunk(db, tmp_path, monkeypatch):
    """与图片无关的 chunk 不被写 metadata、正文也不被改动。"""
    url = "https://cdn.example.com/a.png"
    md = _write_md(tmp_path, f"![图]({url})")
    doc = MarkdownParser().parse(md)
    _capture_chat(monkeypatch)

    with_img = Chunk(text=f"前段 ![图]({url}) 后段", metadata={})
    without = Chunk(text="与图片无关的正文", metadata={})

    await image_service.attach_images(
        [with_img, without], doc.images, md, "note.md",
        Vault(id=1, user_id="default"), _runtime(),
    )

    assert without.text == "与图片无关的正文"
    assert without.metadata.get("images") is None
    assert len(with_img.metadata["images"]) == 1
    assert image_service.IMAGE_MARKER_START in with_img.text
    assert f"![图]({url})" not in with_img.text


@pytest.mark.asyncio
async def test_same_image_in_two_chunks_shares_one_cache_row(db, tmp_path, monkeypatch):
    """overlap 让同一张图落入相邻两片时：两片都记录，但只调一次模型、共用一行缓存。"""
    url = "https://cdn.example.com/a.png"
    raw = f"![图]({url})"
    md = _write_md(tmp_path, raw)
    doc = MarkdownParser().parse(md)
    calls = _capture_chat(monkeypatch, reply="描述")

    chunks = [
        Chunk(text=f"A {raw}", metadata={}),
        Chunk(text=f"B {raw}", metadata={}),
    ]
    await image_service.attach_images(
        chunks, doc.images, md, "note.md", Vault(id=1, user_id="default"), _runtime()
    )

    assert len(calls) == 1
    uids = [c.metadata["images"][0]["uid"] for c in chunks]
    assert uids[0] == uids[1]
    assert len(await _cache_rows()) == 1


# ===== 哪个 LLM 支持图片输入：resolve_image_runtime 的返回情况 =====


async def _add_profile(
    kind="llm", name="m", model="m", multimodal=False,
    is_default=False, enabled=True, user_id="default",
):
    """建一条模型配置；multimodal 决定 params.multimodal。"""
    params = {"multimodal": True} if multimodal else {}
    async with database.session_scope() as session:
        p = await model_repo.create_profile(
            session, user_id=user_id, kind=kind, name=name, model=model,
            base_url="", api_key="k",
            params_json=json.dumps(params), is_default=is_default,
        )
        if not enabled:
            p = await model_repo.update_profile(session, p, {"enabled": False})
        return p.id


async def _resolve(user_id="default"):
    async with database.session_scope() as session:
        return await model_service.resolve_image_runtime(session, user_id)


def test_profile_supports_image_pure_logic():
    """纯判定：只有 kind=llm 且 params.multimodal 为真才支持；params 非法 JSON 视作不支持。"""
    assert model_service.profile_supports_image(
        ModelProfile(kind="llm", name="n", model="m", params_json='{"multimodal": true}')
    ) is True
    # 非 llm 即使带标记也不算
    assert model_service.profile_supports_image(
        ModelProfile(kind="embed", name="n", model="m", params_json='{"multimodal": true}')
    ) is False
    assert model_service.profile_supports_image(
        ModelProfile(kind="llm", name="n", model="m", params_json="{}")
    ) is False
    assert model_service.profile_supports_image(
        ModelProfile(kind="llm", name="n", model="m", params_json="{not json")
    ) is False


@pytest.mark.asyncio
async def test_resolve_none_when_no_llm(db):
    """一个 LLM 都没配 → None（调用方跳过图片处理，不报错）。"""
    assert await _resolve() is None


@pytest.mark.asyncio
async def test_resolve_returns_default_multimodal(db):
    """默认 LLM 支持图片 → 直接返回它，且 kind/params 正确带上。"""
    await _add_profile(name="vlm", model="qwen-vl-max", multimodal=True, is_default=True)

    rt = await _resolve()

    assert rt is not None
    assert rt.kind == "llm"
    assert rt.model == "qwen-vl-max"
    assert rt.params.get("multimodal") is True
    assert image_service.is_supported(rt) is True


@pytest.mark.asyncio
async def test_resolve_prefers_default_when_multimodal(db):
    """多个多模态 LLM 时优先默认项（而不是列表首个）。"""
    await _add_profile(name="other", model="other-vlm", multimodal=True)
    await _add_profile(name="main", model="main-vlm", multimodal=True, is_default=True)

    assert (await _resolve()).model == "main-vlm"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_any_multimodal(db):
    """默认 LLM 是纯文本 → 退而取任一启用的多模态 LLM。"""
    await _add_profile(name="chat", model="qwen-max", multimodal=False, is_default=True)
    await _add_profile(name="vlm", model="qwen-vl-plus", multimodal=True)

    assert (await _resolve()).model == "qwen-vl-plus"


@pytest.mark.asyncio
async def test_resolve_none_when_all_text_only(db):
    """全是纯文本 LLM → None（图片被跳过，索引照常）。"""
    await _add_profile(name="a", model="qwen-max", multimodal=False, is_default=True)
    await _add_profile(name="b", model="glm-4", multimodal=False)

    assert await _resolve() is None


@pytest.mark.asyncio
async def test_resolve_ignores_disabled_multimodal(db):
    """被禁用的多模态 LLM 不参与解析。"""
    await _add_profile(name="vlm", model="qwen-vl-max", multimodal=True, enabled=False)

    assert await _resolve() is None


@pytest.mark.asyncio
async def test_resolve_ignores_non_llm_kind(db):
    """embed 配置即使带 multimodal 标记，也不会被当作图片 LLM。"""
    await _add_profile(kind="embed", name="emb", model="bge-m3", multimodal=True)

    assert await _resolve() is None


@pytest.mark.asyncio
async def test_resolve_isolated_per_user(db):
    """多用户隔离：别人的多模态 LLM 不会被解析到。"""
    await _add_profile(name="vlm", model="qwen-vl-max", multimodal=True, user_id="u1")

    assert await _resolve("u2") is None
    assert (await _resolve("u1")).model == "qwen-vl-max"
