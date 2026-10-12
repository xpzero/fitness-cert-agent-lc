#!/usr/bin/env python3
"""重建检索金标准：按当前全库（148 文档）分层采样生成考生问题。

与首轮 build_golden 的区别：
- 分层采样：每个文档按 chunk 数加权 + 每文档最多 2 条（首轮集中少数文档）
- 双相关：期望集 = 该问题句向量近邻的多个 chunk（不只生成出处一个）
- 覆盖中英教材（检索 miss 里跨语言是大头）

输出 eval/golden/rag_qa_v2.jsonl；导入评测中心用：
  .venv/bin/python eval/scripts/rebuild_golden_v2.py --import-db
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT, settings
from app.db import get_engine, init_db
from app.llm import llm_client
from app.rag.embedder import embedder

N_PER_DOC_MAX = 2
MIN_LEN = 150
TARGET = 120
SEED = 7


def sample_chunks() -> dict[str, list[dict]]:
    """每文档最多 N 条、chunk 足够长；按文档加权凑 TARGET。"""
    rng = random.Random(SEED)
    with get_engine().connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT c.id, c.document_id, c.page_no, left(c.content, 400) AS head,
                   d.title, d.status
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'indexed' AND length(c.content) >= :ml
        """), {"ml": MIN_LEN}).mappings().all()
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_doc[r["document_id"]].append(dict(r))
    picked: dict[str, list[dict]] = {}
    total = 0
    # 轮转每文档取 1 条，直到 TARGET 或取满 N_PER_DOC_MAX
    for round_i in range(N_PER_DOC_MAX):
        for doc_id in sorted(by_doc, key=lambda k: rng.random()):
            if total >= TARGET:
                return picked
            pool = [c for c in by_doc[doc_id] if c not in picked.get(doc_id, [])]
            if not pool:
                continue
            c = rng.choice(pool)
            picked.setdefault(doc_id, []).append(c)
            total += 1
    return picked


def gen_query(chunk: dict) -> str | None:
    """LLM 由 chunk 内容生成"考生会问的口语问题"。"""
    prompt = (
        "你是健身教练考生。根据以下教材内容，写一个备考考生会问的真实问题"
        "（口语化、像在问教练，不照抄原文表述；中文提问，即使材料是英文教材）。\n"
        "只输出 JSON：{\"query\": \"…\"}\n\n"
        f"材料（{chunk['title']} P{chunk['page_no']}）：\n{chunk['head']}")
    try:
        return str(llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            model_tier="fast", max_tokens=200).get("query") or "").strip()
    except Exception:  # noqa: BLE001
        return None


def expand_relevant(seed_chunk_id: str, n: int = 5) -> list[str]:
    """期望集扩展：以出处 chunk 向量为锚的近邻（近邻多 chunk 都算相关）。"""
    with get_engine().connect() as conn:
        row = conn.execute(sql_text(
            "SELECT embedding::text FROM chunks WHERE id = :i"),
            {"i": seed_chunk_id}).first()
    if not row:
        return [seed_chunk_id]
    with get_engine().connect() as conn:
        near = conn.execute(sql_text("""
            SELECT id FROM chunks
            WHERE id != :i
            ORDER BY embedding <-> CAST(:v AS vector) LIMIT :n
        """), {"i": seed_chunk_id, "v": row[0], "n": n}).scalars().all()
    return [seed_chunk_id] + list(near)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import-db", action="store_true", help="导入评测中心（retrieval 类别清空重灌）")
    args = ap.parse_args()

    init_db()
    picked = sample_chunks()
    total = sum(len(v) for v in picked.values())
    print(f"采样：{len(picked)} 文档 / {total} chunks（目标 {TARGET}）")

    out = []
    for doc_id, chunks in picked.items():
        for c in chunks:
            q = gen_query(c)
            if not q or len(q) < 8:
                print(f"  跳过（生成失败）：{c['title'][:30]}")
                continue
            rel = expand_relevant(c["id"])
            out.append({"query": q, "relevant_chunk_ids": rel, "auto": True,
                        "seed_chunk": c["id"], "doc": c["title"][:40]})
            print(f"  ✓ {q[:36]}  ({c['title'][:24]} P{c['page_no']})")

    path = PROJECT_ROOT / "eval/golden/rag_qa_v2.jsonl"
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out))
    print(f"完成：{len(out)} 条 → {path}")

    if args.import_db:
        from app.services import eval_service as es

        es.init_eval_tables()
        with get_engine().begin() as conn:
            conn.execute(sql_text(
                "DELETE FROM eval_cases WHERE kind = 'retrieval'"))
        n = es.import_cases("retrieval", "rag_qa_v2.jsonl")
        # import 读固定文件名——v2 文件直接按 kind 映射灌入
        print(f"已导入评测中心：{n} 新增（retrieval 共 {len(es.list_cases('retrieval'))} 条）")


if __name__ == "__main__":
    main()
