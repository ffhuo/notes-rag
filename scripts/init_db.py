"""建表脚本 — 初始化 SQLite 表结构（可独立运行）。

能力：
- 调用 core.database.init_db 创建 notes / chunks / conversations / messages 四张表
- 作为命令直接运行：python scripts/init_db.py

主要逻辑：
- 载入配置（settings）
- 调用 await init_db()

关联方案：docs/design.md §6（数据模型）。
"""
import asyncio

from app.core.database import init_db


if __name__ == "__main__":
    asyncio.run(init_db())
