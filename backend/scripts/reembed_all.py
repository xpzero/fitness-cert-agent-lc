#!/usr/bin/env python3
"""全库重嵌入迁移（换 embedding 模型 + chunk 上下文前缀，一次完成）。

背景：bge-small-zh(512d) → multilingual-e5-large(1024d)，中英互检能力是
检索 miss 的主要病灶之一；同时给每个 chunk 的嵌入文本前置文档标题+章节
路径（Anthropic Contextual Retrieval 的元数据版），让 dense 能区分出处。

步骤：
1. DB 列 vector(512) → vector(1024)（重建 HNSW 索引）
2. 全量 chunk 逐批重嵌入：前缀 "【书名·章节】" + 原文（e5 加 passage: 前缀）
3. 断点续跑：已迁移的 chunk（embedding_model 标记）跳过

用法：.venv/bin/python scripts/reembed_all.py [--batch 64]
预计：9.4 万块 × ~15ms/块 ≈ 25 分钟（CPU）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT, settings
from app.db import database, init_db


def ensure_columns() -> None:
    """chunks 加 embed_meta 列（记录嵌入用的模型+前缀，断点续跑依据）。"""
    with database.engine.begin() as conn:
        conn.execute(sql_text(
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embed_meta TEXT DEFAULT ''"))


def migrate_dimension(new_dim: int) -> None:
    """vector(512) → vector(new_dim)：改列类型 + 重建 HNSW 索引。"""
    with database.engine.begin() as conn:
        dim = conn.execute(sql_text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid='chunks'::regclass AND attname='embedding'")).scalar()
        if dim == new_dim:
            print(f"维度已是 {new_dim}，跳过")
            return
        print(f"迁移维度 {dim} → {new_dim}（清空旧向量，重建索引）")
        conn.execute(sql_text("DROP INDEX IF EXISTS idx_chunks_embedding"))
        conn.execute(sql_text("UPDATE chunks SET embedding = NULL"))
        # ALTER TYPE 需要字面维度，不能用绑定参数
        conn.execute(sql_text(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({new_dim})"))
        conn.execute(sql_text(
            "CREATE INDEX idx_chunks_embedding ON chunks "
            "USING hnsw (embedding vector_cosine_ops)"))


def prefixed_content(chunk_id: str, title: str, section: str, content: str) -> str:
    """嵌入文本 = 元数据前缀 + 原文。前缀只进向量，不改正文（展示/引用不变）。"""
    prefix = f"【{title[:40]}" + (f"·{section[:24]}" if section else "") + "】"
    return prefix + content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    init_db()
    ensure_columns()
    new_dim = settings.embed_dim
    migrate_dimension(new_dim)

    from app.rag.embedder import embedder

    model_tag = f"{settings.embed_model}+prefix"
    t0 = time.time()
    done = 0
    while True:
        with database.engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT c.id, c.content, c.section_path, d.title
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NULL OR c.embed_meta != :tag
                ORDER BY c.id LIMIT :n
            """), {"tag": model_tag, "n": args.batch}).mappings().all()
        if not rows:
            break
        texts = [prefixed_content(r["id"], r["title"], r["section_path"], r["content"])
                 for r in rows]
        vectors = embedder.embed_passages(texts)
        with database.engine.begin() as conn:
            for r, v in zip(rows, vectors):
                conn.execute(sql_text(
                    "UPDATE chunks SET embedding = CAST(:v AS vector), "
                    "embed_meta = :tag WHERE id = :i"),
                    {"v": "[" + ",".join(f"{x:.6f}" for x in v) + "]",
                     "tag": model_tag, "i": r["id"]})
        done += len(rows)
        if done % (args.batch * 10) == 0:
            rate = done / max(1, time.time() - t0)
            eta = (94498 - done) / max(0.1, rate) / 60
            print(f"  已重嵌入 {done}（{rate:.1f}/s，预计剩余 {eta:.0f} 分钟）", flush=True)
    print(f"完成：共 {done} 块，耗时 {(time.time()-t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
