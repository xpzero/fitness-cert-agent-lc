"""数据库引擎与会话；database.init_db() 建表 + 启用扩展 + 建索引。"""
from __future__ import annotations

from functools import cached_property

from sqlalchemy import create_engine, text

from app.config import settings


class Database:
    """数据库入口：engine 懒创建（cached_property，import 本模块不建连接）。"""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.database_url

    @cached_property
    def engine(self):
        # 多子图节点高频短查询：显式上下文管理之外，池子留足余量防 GC 延迟泄漏
        return create_engine(self._url, pool_pre_ping=True, future=True,
                             pool_size=10, max_overflow=20, pool_timeout=30)

    def init_db(self) -> None:
        """建表 + pg_trgm（中文 trigram 稀疏检索用，替代 zhparser）+ 索引。

        迁移策略（无 Alembic，保持轻量）：
        - 新库：Base.metadata.create_all 一次建全（含 tables.py 内声明的 HNSW/trgm 索引）
        - 旧库：create_all 不迁移已存表——下方 ALTER 与 CREATE INDEX IF NOT EXISTS
          逐项兜底；给 documents 加列时需同时改 tables.py 的 Document 模型（两处保持同步）
        """
        from pgvector.sqlalchemy import Vector  # noqa: F401  确保类型已注册

        from app.models.tables import Base

        engine = self.engine
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            # documents 生命周期列（M1）：与 tables.Document 模型同步维护
            conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'indexed'"))
            conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS filename VARCHAR(256) DEFAULT ''"))
            conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error TEXT DEFAULT ''"))
            conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"))
            conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()"))
        with engine.begin() as conn:
            # 检索索引（与 tables.Chunk.__table_args__ 同名同定义；此处覆盖旧库路径）
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
                "ON chunks USING hnsw (embedding vector_cosine_ops)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm "
                "ON chunks USING gin (content gin_trgm_ops)"
            ))


database = Database()  # 进程级单例（懒初始化，首次用才建 engine）


# --------------------------------------------------------------- 兼容层
# get_engine / init_db 是旧的函数入口：graphs 内部与 scripts/eval 的调用点
# 尚未迁移，经此薄委托保持可用；新代码请直接用 database.engine / database.init_db()。
def get_engine():
    return database.engine


def init_db() -> None:
    database.init_db()
