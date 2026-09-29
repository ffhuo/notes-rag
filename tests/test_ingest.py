"""摄取接口测试 — 验证 /ingest 在 mock embedding 下跑通。

能力：
- 用 conftest 提供的临时 vault 与 mock embedder
- 调 POST /api/v1/ingest，断言返回的 scanned / indexed_chunks 合理
- 断言向量库与 SQLite 元数据已写入

关联方案：docs/design.md §9.1（测试与质量）。
"""


def test_ingest_runs():
    ...
