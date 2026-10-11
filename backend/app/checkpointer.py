"""LangGraph checkpoint 持久化（PostgresSaver）。

HITL 中断草稿跨进程/跨重启可恢复——规划确认可以隔天再来。
checkpoint 表与业务表同库（init_db 建业务表，saver.setup() 建 checkpoint 表）。
"""
from __future__ import annotations

from functools import lru_cache

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from app.config import settings


@lru_cache
def get_checkpointer() -> PostgresSaver:
    uri = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(uri, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()  # 幂等：建 checkpoint 表
    return saver
