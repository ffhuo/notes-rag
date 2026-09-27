"""chunker 单元测试 — 覆盖 split / split_markdown / split_html / split_text。

测试维度：
1. 基础切分：短文本不切、空文本返回空
2. 递归切分：长文本按分隔符降级、overlap 合并
3. Markdown：标题层级、面包屑、heading 元数据
4. HTML：标题切分、去标签、降级
5. Chunk 结构：metadata 字段完整性、extra_metadata 合并
6. offset：char_start/char_end 指向正确位置
7. 边界：单字符、纯空白、超长无分隔符文本
8. 真实文件切分：读取 .md / .html / .txt 文件验证
"""

from pathlib import Path

from app.rag.chunker import (
    Chunk,
    FORMAT_HTML,
    FORMAT_MARKDOWN,
    FORMAT_TEXT,
    split,
    split_html,
    split_markdown,
    split_text,
)


# ===== 1. 基础切分 =====


class TestBasic:
    def test_short_text_no_split(self):
        """短文本不超过 max_chars，不切分。"""
        chunks = split_text("短文本", max_chars=800)
        assert len(chunks) == 1
        assert chunks[0].text == "短文本"

    def test_empty_text(self):
        """空文本返回空列表。"""
        assert split_text("") == []
        assert split_text("   \n  \t ") == []

    def test_exact_max_chars(self):
        """文本长度恰好等于 max_chars，不切分。"""
        text = "a" * 800
        chunks = split_text(text, max_chars=800)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_split_returns_chunk_instances(self):
        """split 返回的是 Chunk 实例。"""
        chunks = split("测试", fmt=FORMAT_TEXT)
        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)

    def test_split_empty_all_formats(self):
        """所有格式的空文本都返回空列表。"""
        assert split("", fmt=FORMAT_TEXT) == []
        assert split("", fmt=FORMAT_MARKDOWN) == []
        assert split("", fmt=FORMAT_HTML) == []


# ===== 2. 递归切分 =====


class TestRecursiveSplit:
    def test_long_text_multiple_chunks(self):
        """长文本产生多个片段。"""
        text = "段落内容。" * 200
        chunks = split_text(text, max_chars=400)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c.text) <= 600  # 允许少量超出（merge 时加分隔符）

    def test_paragraph_boundary(self):
        """按段落边界切分，不截断句子。"""
        text = "第一段内容。句子一。\n\n第二段内容。句子二。\n\n第三段内容。句子三。"
        chunks = split_text(text, max_chars=20)
        assert len(chunks) >= 2
        # 每个 chunk 不应在句中硬切（至少以句子结尾或段落结尾）
        # 注意：overlap 可能导致首尾有重叠文本

    def test_separator_degradation(self):
        """分隔符逐级降级：无段落分隔时用换行，无换行用句号。"""
        text = "句子一。句子二。句子三。句子四。句子五。"
        chunks = split_text(text, max_chars=15)
        assert len(chunks) >= 2

    def test_no_separator_hard_split(self):
        """无任何分隔符的超长文本，最终硬切。"""
        text = "a" * 1000
        chunks = split_text(text, max_chars=200, overlap=False)
        assert len(chunks) >= 5
        for c in chunks:
            assert len(c.text) <= 200

    def test_overlap_produces_overlapping_content(self):
        """overlap=True 时相邻片段有内容重叠。"""
        text = "A。B。C。D。E。F。G。H。I。J。K。L。M。N。O。P。Q。R。S。T。" * 10
        chunks = split_text(text, max_chars=100, overlap=True)
        assert len(chunks) >= 2
        # 第二个 chunk 的开头应来自第一个 chunk 的尾部
        first_tail = chunks[0].text[-15:]
        second_head = chunks[1].text[:15]
        # 至少有部分字符重叠
        assert any(
            first_tail[i:] in second_head
            for i in range(len(first_tail))
        ), f"overlap 内容应重叠: tail={first_tail}, head={second_head}"

    def test_no_overlap_disjoint(self):
        """overlap=False 时片段间无重叠。"""
        text = "A。B。C。D。E。F。G。H。I。J。K。L。M。N。O。P。Q。R。S。T。" * 10
        chunks = split_text(text, max_chars=100, overlap=False)
        # 无 overlap 时片段总数应少于有 overlap 的
        chunks_overlap = split_text(text, max_chars=100, overlap=True)
        assert len(chunks) <= len(chunks_overlap)


# ===== 3. Markdown 切分 =====


class TestMarkdownSplit:
    def test_heading_breadcrumb(self):
        """多级标题生成正确面包屑。"""
        md = "# 第一章\n\n正文一。\n\n## 第一节\n\n正文二。"
        chunks = split_markdown(md, max_chars=800)
        assert len(chunks) == 2
        assert chunks[0].metadata["breadcrumb"] == "第一章"
        assert chunks[1].metadata["breadcrumb"] == "第一章 > 第一节"

    def test_heading_metadata(self):
        """每个 chunk 携带 heading 字段。"""
        md = "# 标题A\n\n内容。\n\n## 标题B\n\n更多内容。"
        chunks = split_markdown(md, max_chars=800)
        assert chunks[0].metadata["heading"] == "标题A"
        assert chunks[1].metadata["heading"] == "标题B"

    def test_no_heading_degrades_to_text(self):
        """无标题 Markdown 降级为递归切分。"""
        md = "无标题纯文本。句子。" * 200
        chunks = split_markdown(md, max_chars=400)
        assert len(chunks) >= 2
        # 无面包屑
        for c in chunks:
            assert "breadcrumb" not in c.metadata

    def test_deep_heading_levels(self):
        """六级标题嵌套。"""
        md = "# L1\n\na\n\n## L2\n\nb\n\n### L3\n\nc\n\n#### L4\n\nd\n\n##### L5\n\ne\n\n###### L6\n\nf"
        chunks = split_markdown(md, max_chars=800)
        breadcrumbs = [c.metadata.get("breadcrumb", "") for c in chunks]
        assert "L1" in breadcrumbs[0]
        assert "L1 > L2" in breadcrumbs[1]
        assert "L1 > L2 > L3 > L4 > L5 > L6" in breadcrumbs[-1]

    def test_markdown_chunk_index_sequential(self):
        """chunk_index 从 0 开始递增。"""
        md = "# A\n\n" + "内容。" * 200 + "\n\n# B\n\n" + "内容。" * 200
        chunks = split_markdown(md, max_chars=400)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_prefix_in_text(self):
        """面包屑前缀出现在 chunk 文本中。"""
        md = "# 章节标题\n\n正文内容。"
        chunks = split_markdown(md, max_chars=800)
        assert chunks[0].text.startswith("[章节标题]")

    def test_content_before_first_heading(self):
        """标题前的内容作为独立 chunk。"""
        md = "前言内容。\n\n# 第一章\n\n正文。"
        chunks = split_markdown(md, max_chars=800)
        assert len(chunks) == 2
        assert chunks[0].text == "前言内容。"
        assert "breadcrumb" not in chunks[0].metadata or not chunks[0].metadata.get("breadcrumb")


# ===== 4. HTML 切分 =====


class TestHtmlSplit:
    def test_heading_breadcrumb(self):
        """HTML 标题生成面包屑。"""
        html = "<h1>标题一</h1><p>正文一</p><h2>标题二</h2><p>正文二</p>"
        chunks = split_html(html, max_chars=800)
        assert len(chunks) == 2
        assert chunks[0].metadata["breadcrumb"] == "标题一"
        assert chunks[1].metadata["breadcrumb"] == "标题一 > 标题二"

    def test_strips_tags(self):
        """chunk 文本不含 HTML 标签。"""
        html = "<h1>标题</h1><p>这是<b>加粗</b>的正文</p>"
        chunks = split_html(html, max_chars=800)
        for c in chunks:
            assert "<" not in c.text
            assert ">" not in c.text

    def test_html_entities_decoded(self):
        """HTML 实体被反转义。"""
        html = "<p>文本 &amp; 更多 &lt;tag&gt; 内容</p>"
        chunks = split_html(html, max_chars=800)
        assert "&" in chunks[0].text
        assert "<" in chunks[0].text
        assert ">" in chunks[0].text

    def test_no_heading_degrades(self):
        """无标题 HTML 降级为递归切分。"""
        html = "<p>无标题段落一</p><p>无标题段落二</p>"
        chunks = split_html(html, max_chars=800)
        assert len(chunks) == 1
        assert "breadcrumb" not in chunks[0].metadata

    def test_heading_with_attributes(self):
        """带属性的 h 标签仍可解析。"""
        html = '<h1 class="title" id="t1">标题</h1><p>正文</p>'
        chunks = split_html(html, max_chars=800)
        assert chunks[0].metadata["heading"] == "标题"


# ===== 5. Chunk 结构与 metadata =====


class TestChunkMetadata:
    def test_chunk_has_required_fields(self):
        """每个 chunk 包含 chunk_index / char_start / char_end。"""
        chunks = split_text("测试文本内容", max_chars=800)
        m = chunks[0].metadata
        assert "chunk_index" in m
        assert "char_start" in m
        assert "char_end" in m

    def test_extra_metadata_merged(self):
        """extra_metadata 被合并到每个 chunk。"""
        chunks = split_text(
            "测试",
            max_chars=800,
            extra_metadata={"page": 3, "source_file": "test.txt"},
        )
        assert chunks[0].metadata["page"] == 3
        assert chunks[0].metadata["source_file"] == "test.txt"
        # 原有字段仍在
        assert chunks[0].metadata["chunk_index"] == 0

    def test_extra_metadata_in_markdown(self):
        """Markdown 切分也合并 extra_metadata。"""
        md = "# 标题\n\n正文。"
        chunks = split_markdown(md, max_chars=800, extra_metadata={"page": 1})
        assert chunks[0].metadata["page"] == 1
        assert chunks[0].metadata["breadcrumb"] == "标题"

    def test_ingest_layer_can_extend_metadata(self):
        """ingest 层可直接操作 chunk.metadata 补充字段。"""
        chunks = split_text("测试", extra_metadata={"page": 1})
        for c in chunks:
            c.metadata["source_file"] = "note.md"
            c.metadata["vault_id"] = 42
            c.metadata["tags"] = '["python","rag"]'
        assert chunks[0].metadata["source_file"] == "note.md"
        assert chunks[0].metadata["vault_id"] == 42
        assert chunks[0].metadata["tags"] == '["python","rag"]'

    def test_empty_breadcrumb_not_in_metadata(self):
        """无面包屑时不写入 breadcrumb 字段。"""
        chunks = split_text("纯文本", max_chars=800)
        assert "breadcrumb" not in chunks[0].metadata
        assert "heading" not in chunks[0].metadata

    def test_chunk_index_sequential(self):
        """chunk_index 从 0 开始连续递增。"""
        text = "段落一。" * 100 + "\n\n" + "段落二。" * 100
        chunks = split_text(text, max_chars=400)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i


# ===== 6. offset 正确性 =====


class TestOffset:
    def test_short_text_offset(self):
        """短文本 offset 覆盖全文。"""
        text = "短文本"
        chunks = split_text(text, max_chars=800)
        assert chunks[0].metadata["char_start"] == 0
        assert chunks[0].metadata["char_end"] == len(text)

    def test_offset_within_bounds(self):
        """所有 chunk 的 offset 在原文范围内。"""
        text = "段落一。" * 100 + "\n\n" + "段落二。" * 100
        stripped = text.strip()
        chunks = split_text(text, max_chars=400)
        for c in chunks:
            assert 0 <= c.metadata["char_start"] < len(stripped)
            assert 0 < c.metadata["char_end"] <= len(stripped)
            assert c.metadata["char_start"] < c.metadata["char_end"]

    def test_offset_points_to_correct_position(self):
        """offset 指向的位置确实是 chunk 内容的起点。"""
        text = "段落一。" * 100 + "\n\n" + "段落二。" * 100
        stripped = text.strip()
        chunks = split_text(text, max_chars=400)
        for c in chunks:
            substr = stripped[c.metadata["char_start"]:c.metadata["char_end"]]
            # chunk 首段应出现在 offset 对应的子串中
            assert c.text[:4] in substr, (
                f"chunk 首段 '{c.text[:10]}' 不在 offset 子串 '{substr[:20]}' 中"
            )


# ===== 7. 边界情况 =====


class TestEdgeCases:
    def test_single_char(self):
        """单字符文本。"""
        chunks = split_text("a", max_chars=800)
        assert len(chunks) == 1
        assert chunks[0].text == "a"

    def test_only_whitespace(self):
        """纯空白返回空。"""
        assert split_text("   \n\n\t  ") == []

    def test_super_long_no_separator(self):
        """超长无分隔符文本硬切。"""
        text = "a" * 5000
        chunks = split_text(text, max_chars=200, overlap=False)
        assert len(chunks) >= 20
        for c in chunks:
            assert len(c.text) <= 200

    def test_max_chars_too_small(self):
        """max_chars 极小时仍能切分。"""
        text = "abc"
        chunks = split_text(text, max_chars=1, overlap=False)
        assert len(chunks) == 3

    def test_uniform_entry_point(self):
        """split() 统一入口与直接调用等价。"""
        text = "测试文本"
        assert split(text, fmt=FORMAT_TEXT) == split_text(text)
        assert len(split(text, fmt=FORMAT_MARKDOWN)) == len(split_markdown(text))
        assert len(split(text, fmt=FORMAT_HTML)) == len(split_html(text))


# ===== 8. 真实文件切分 =====

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestFileSplitMarkdown:
    """读取真实 .md 文件切分。"""

    def setup_method(self):
        self.path = FIXTURES_DIR / "sample.md"
        self.text = self.path.read_text(encoding="utf-8")

    def test_produces_chunks(self):
        """能从 md 文件切出多个 chunk。"""
        chunks = split(self.text, fmt=FORMAT_MARKDOWN, max_chars=300)
        assert len(chunks) >= 3
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.text.strip()

    def test_chunk_index_sequential(self):
        """chunk_index 从 0 递增。"""
        chunks = split(self.text, fmt=FORMAT_MARKDOWN, max_chars=200)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_extra_metadata_in_file_chunks(self):
        """文件切分支持 extra_metadata。"""
        chunks = split(
            self.text,
            fmt=FORMAT_MARKDOWN,
            max_chars=800,
            extra_metadata={"source_file": "sample.md"},
        )
        # chunks 内容写到测试文件
        with open(FIXTURES_DIR / "md_result.md", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write("\n\n------------------------start------------------------\n")
                f.write(c.text + "\n\n")
                f.write("\n\n------------------------metadata------------------------\n")
                f.write("\n".join(f"{k}: {v}" for k, v in c.metadata.items()))
                f.write("\n\n------------------------end------------------------\n")

        assert chunks[0].metadata["source_file"] == "sample.md"

    def test_text_content_preserved(self):
        """chunk 文本中包含原文关键内容。"""
        chunks = split(self.text, fmt=FORMAT_MARKDOWN, max_chars=800)
        all_text = "".join(c.text for c in chunks)
        assert "Python" in all_text
        assert "asyncio" in all_text
        assert "装饰器" in all_text


class TestFileSplitHtml:
    """读取真实 .html 文件切分。"""

    def setup_method(self):
        self.path = FIXTURES_DIR / "sample.html"
        self.text = self.path.read_text(encoding="utf-8")

    def test_produces_chunks(self):
        """能从 html 文件切出多个 chunk。"""
        chunks = split(self.text, fmt=FORMAT_HTML, max_chars=300)
        assert len(chunks) >= 3
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.text.strip()

    def test_strips_html_tags_from_file(self):
        """chunk 文本不含 HTML 标签。"""
        chunks = split(self.text, fmt=FORMAT_HTML, max_chars=800)
        for c in chunks:
            assert "<h" not in c.text
            assert "<p>" not in c.text
            assert "</" not in c.text

    def test_breadcrumbs_match_headings(self):
        """面包屑与 HTML 标题对应。"""
        chunks = split(self.text, fmt=FORMAT_HTML, max_chars=800)
        breadcrumbs = [c.metadata.get("breadcrumb", "") for c in chunks]
        assert any("FastAPI 教程" in b for b in breadcrumbs)
        assert any("FastAPI 教程 > 快速开始" in b for b in breadcrumbs)
        assert any("FastAPI 教程 > 数据模型" in b for b in breadcrumbs)

    def test_chunk_index_sequential(self):
        """chunk_index 从 0 递增。"""
        chunks = split(self.text, fmt=FORMAT_HTML, max_chars=200)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_text_content_preserved(self):
        """chunk 文本中包含原文关键内容。"""
        chunks = split(self.text, fmt=FORMAT_HTML, max_chars=800)
        all_text = "".join(c.text for c in chunks)
        assert "FastAPI" in all_text
        assert "Uvicorn" in all_text
        assert "Pydantic" in all_text


class TestFileSplitText:
    """读取真实 .txt 文件切分。"""

    def setup_method(self):
        self.path = FIXTURES_DIR / "sample.txt"
        self.text = self.path.read_text(encoding="utf-8")

    def test_produces_chunks(self):
        """能从 txt 文件切出多个 chunk。"""
        chunks = split(self.text, fmt=FORMAT_TEXT, max_chars=300)
        assert len(chunks) >= 3
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.text.strip()

    def test_no_breadcrumb_in_text_chunks(self):
        """纯文本切分不产生 breadcrumb。"""
        chunks = split(self.text, fmt=FORMAT_TEXT, max_chars=800)
        for c in chunks:
            assert "breadcrumb" not in c.metadata
            assert "heading" not in c.metadata

    def test_chunk_index_sequential(self):
        """chunk_index 从 0 递增。"""
        chunks = split(self.text, fmt=FORMAT_TEXT, max_chars=200)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_offset_within_bounds(self):
        """所有 chunk 的 offset 在文件文本范围内。"""
        stripped = self.text.strip()
        chunks = split(self.text, fmt=FORMAT_TEXT, max_chars=200)
        for c in chunks:
            assert 0 <= c.metadata["char_start"] < len(stripped)
            assert 0 < c.metadata["char_end"] <= len(stripped)
            assert c.metadata["char_start"] < c.metadata["char_end"]

    def test_text_content_preserved(self):
        """chunk 文本中包含原文关键内容。"""
        chunks = split(self.text, fmt=FORMAT_TEXT, max_chars=800)
        all_text = "".join(c.text for c in chunks)
        assert "Goroutine" in all_text
        assert "Channel" in all_text
        assert "select" in all_text
        assert "context" in all_text

    def test_extra_metadata_in_file_chunks(self):
        """文件切分支持 extra_metadata。"""
        chunks = split(
            self.text,
            fmt=FORMAT_TEXT,
            max_chars=800,
            extra_metadata={"source_file": "sample.txt"},
        )
        assert chunks[0].metadata["source_file"] == "sample.txt"


# ===== 9. 表格保护 =====


class TestMarkdownTableProtection:
    """Markdown pipe table 切分保护。"""

    def test_table_not_split_mid_row(self):
        """小表格保持完整，不被拆散。"""
        md = (
            "# 表格测试\n\n"
            "前言文本。\n\n"
            "| 姓名 | 年龄 | 城市 |\n|------|------|------|\n| 张三 | 25 | 北京 |\n\n"
            "后续文本。"
        )
        chunks = split_markdown(md, max_chars=100)
        # 至少有一个 chunk 包含完整表格
        table_chunks = [c for c in chunks if "|" in c.text and "---" in c.text]
        assert len(table_chunks) >= 1
        for tc in table_chunks:
            assert "张三" in tc.text

    def test_large_table_splits_with_repeated_header(self):
        """大表格按行切分时，每个子表都带表头。"""
        rows = [f"| 项目{i} | 描述内容{i} |" for i in range(20)]
        md = f"# 大表\n\n| 名称 | 描述 |\n|------|------|\n" + "\n".join(rows)
        chunks = split_markdown(md, max_chars=80)
        table_chunks = [c for c in chunks if "| 名称 |" in c.text]
        assert len(table_chunks) >= 2  # 被拆分成多个子表
        for tc in table_chunks:
            assert "| 名称 |" in tc.text  # 每个子表都有表头
            assert "|------|------|" in tc.text  # 都有分隔行

    def test_table_with_surrounding_text(self):
        """表格前后的文本独立切分，不混入表格。"""
        md = (
            "# 章节\n\n"
            "这是表格前的内容。\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "这是表格后的内容。\n\n"
        )
        chunks = split_markdown(md, max_chars=100)
        # 有不含表格的文本 chunk
        text_chunks = [c for c in chunks if "|---|" not in c.text]
        assert any("表格前" in c.text for c in text_chunks)
        assert any("表格后" in c.text for c in text_chunks)

    def test_no_table_normal_split(self):
        """无表格时正常切分。"""
        md = "# 标题\n\n正文内容一。\n\n正文内容二。"
        chunks = split_markdown(md, max_chars=800)
        assert len(chunks) == 1  # 内容不超限，1 块


class TestHtmlTableProtection:
    """HTML table 切分保护。"""

    def test_html_table_converted_to_pipe_table(self):
        """HTML 表格转为 pipe table 格式后保护。"""
        html = (
            "<h1>报告</h1>"
            "<table>"
            "<tr><th>指标</th><th>值</th></tr>"
            "<tr><td>CPU</td><td>80%</td></tr>"
            "</table>"
            "<p>结论。</p>"
        )
        chunks = split_html(html, max_chars=100)
        # 应有包含 pipe table 的 chunk
        table_chunks = [c for c in chunks if "|---" in c.text]
        assert len(table_chunks) >= 1
        assert "CPU" in table_chunks[0].text

    def test_large_html_table_splits_with_header(self):
        """大 HTML 表格按行切分，每个子表带表头。"""
        rows = "".join(
            f"<tr><td>项目{i}</td><td>描述{i}</td></tr>" for i in range(20)
        )
        html = (
            "<h1>大表</h1>"
            "<table>"
            "<tr><th>名称</th><th>描述</th></tr>"
            f"{rows}"
            "</table>"
        )
        chunks = split_html(html, max_chars=80)
        table_chunks = [c for c in chunks if "| 名称 |" in c.text]
        assert len(table_chunks) >= 2
        for tc in table_chunks:
            assert "| 名称 |" in tc.text

    def test_html_table_no_tags_in_output(self):
        """HTML 表格转换后 chunk 不含 HTML 标签。"""
        html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        chunks = split_html(html, max_chars=800)
        for c in chunks:
            assert "<table" not in c.text
            assert "<tr" not in c.text


# ===== 10. 图片预处理 =====


class TestImagePreprocessing:
    """Markdown 图片收集测试。"""

    def test_image_urls_collected(self):
        """图片 URL 被收集，原文不改写。"""
        from app.parsers.markdown import collect_images

        text = "正文 ![架构图](img/arch.png) 后续 ![](img/noalt.png)"
        images = collect_images(text)
        assert images == ["img/arch.png", "img/noalt.png"]
        # 原文未被修改
        assert "![架构图](img/arch.png)" in text

    def test_no_images_returns_empty(self):
        """无图片时返回空列表。"""
        from app.parsers.markdown import collect_images

        assert collect_images("纯文本无图片") == []

    def test_parser_preserves_original_format(self):
        """parser 不改写原文，保留图片语法。"""
        import os
        import tempfile
        from pathlib import Path

        from app.parsers.markdown import MarkdownParser

        md = "# 测试\n\n![流程图](img/flow.png)\n\n正文。"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(md)
            f.flush()
            try:
                doc = MarkdownParser().parse(Path(f.name))
                # 原文保留图片语法
                assert "![流程图](img/flow.png)" in doc.content
                # 图片引用存入 images（结构化）
                assert [r.target for r in doc.images] == ["img/flow.png"]
                assert doc.images[0].kind == "md"
            finally:
                os.unlink(f.name)

    def test_three_syntax_kinds(self):
        """三类图片语法（md / obsidian wikilink / 内联 html）均被提取。"""
        from app.parsers.markdown import collect_image_refs

        text = (
            "![外链](https://cdn.example.com/a.png)\n"
            "![[local.png]]\n"
            "![[local2.png|300]]\n"
            "<img src=\"assets/photo.jpg\" alt=\"x\">\n"
        )
        refs = collect_image_refs(text)
        assert [(r.kind, r.target) for r in refs] == [
            ("md", "https://cdn.example.com/a.png"),
            ("wiki", "local.png"),
            ("wiki", "local2.png"),
            ("html", "assets/photo.jpg"),
        ]
        # 纯数字别名（尺寸）不当作 alt
        assert refs[2].alt == ""

    def test_wikilink_alias_as_alt(self):
        """Obsidian wikilink 的非数字别名作为 alt。"""
        from app.parsers.markdown import collect_image_refs

        refs = collect_image_refs("![[diagram.png|架构图]]")
        assert refs[0].target == "diagram.png"
        assert refs[0].alt == "架构图"
