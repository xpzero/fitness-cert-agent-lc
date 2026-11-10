#!/usr/bin/env python3
"""导出检索 miss 详情供人工清洗金标准：query + seed 原文 + 实际 top5 原文。

用途：run_retrieval_eval 的报告只含期望 id 列表（无内容），人工判断"检回的
是否其实回答了问题"需要看双方原文。本脚本复用同一命中判定逻辑，把每个
miss 的 query、金标准 seed chunk 原文、实际 top5 chunk 原文写成 markdown，
逐条勾选：检回相关 → 把 chunk id 补进该条 relevant_chunk_ids（标签修正）；
检回无关 → 保留 miss（真检索缺口）。

用法：.venv/bin/python eval/scripts/dump_misses.py [--golden rag_qa_v2.jsonl] [--top 5]
输出：eval/report/misses-detail.md（gitignored 工作产物）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT
from app.db import get_engine, init_db
from app.rag.search import searcher


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="rag_qa_v2.jsonl")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    init_db()
    engine = get_engine()
    cases = [json.loads(l) for l in
             (PROJECT_ROOT / "eval/golden" / args.golden).read_text().splitlines()
             if l.strip()]
    print(f"金标准：{len(cases)} 条（{args.golden}）")

    with engine.connect() as conn:
        all_vecs = {r[0]: json.loads(r[1]) for r in conn.execute(
            sql_text("SELECT id, embedding::text FROM chunks")).all()}
        rows = conn.execute(sql_text(
            "SELECT c.id, c.page_no, c.section_path, c.content, c.document_id, d.title "
            "FROM chunks c JOIN documents d ON d.id = c.document_id")).mappings().all()
    by_id = {r["id"]: r for r in rows}

    def expand_relevant(cid: str) -> set[str]:
        if cid not in all_vecs:
            return set()
        base = np.array(all_vecs[cid])
        out = {cid}
        for other, vec in all_vecs.items():
            if other != cid and float(np.dot(base, np.array(vec)) /
                                      (np.linalg.norm(base) * np.linalg.norm(vec) + 1e-9)) >= 0.80:
                out.add(other)
        return out

    def block(cid: str) -> str:
        r = by_id.get(cid)
        if not r:
            return f"  [{cid}] （已失效）"
        return (f"  [{cid}] {r['title']} · P{r['page_no']}\n"
                f"    {r['content'][:280].replace(chr(10), ' ')}")

    out_lines = ["# 检索 miss 详情（人工清洗用）\n"]
    misses = dead = 0
    for i, case in enumerate(cases, 1):
        candidates = searcher.search(case["query"])
        ids = [c.chunk_id for c in candidates[:5]]
        relevant = set().union(*(expand_relevant(c) for c in case["relevant_chunk_ids"]))
        if not relevant:
            dead += 1
            continue  # 全灭用例（另行剔除，不进清洗清单）
        if any(cid in relevant for cid in ids):
            continue
        misses += 1
        seed = case.get("seed_chunk") or case["relevant_chunk_ids"][0]
        out_lines += [
            f"## M{misses}　{case['query']}",
            f"- 金标准 seed（出自《{case.get('doc', '?')}》）：\n{block(seed)}",
            "- 实际检索 top5：",
        ]
        out_lines += [block(c) for c in ids[:args.top]]
        out_lines.append("")
        print(f"  miss {misses}（{i}/{len(cases)}）", flush=True)

    path = PROJECT_ROOT / "eval/report/misses-detail.md"
    path.write_text("\n".join(out_lines))
    print(f"miss {misses} 条 / 全灭 {dead} 条 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
