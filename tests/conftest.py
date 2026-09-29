"""测试夹具 — pytest 配置与共享 fixture。

能力：
- 提供测试用的临时 vault 目录（放几个样例 .md）
- 提供临时 SQLite / 临时 Chroma 目录
- 提供 mock 的 embedder / llm_client（返回固定向量 / 固定流），隔离外部 API
- 提供 TestClient fixture，供接口集成测试使用

主要 fixture（建议）：
- tmp_vault: 生成小样本笔记目录
- mock_embedder / mock_llm: 替换 RAG 组件
- client: FastAPI TestClient

关联方案：docs/design.md §9.1（测试与质量）。
"""
