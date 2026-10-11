#!/usr/bin/env python3
"""引用正确率评测（W7，设计文档 §7 P1 验收遗留项）。

对每条金标准跑完整 qa 子图（改写→检索→生成→引用校验）：
- cite 类：回答未拒答 且 引用的 chunk 命中期望集合（按余弦 ≥0.80 扩展等价碎片，
  与 run_retrieval_eval 同款口径）
- refuse 类：域外问题必须拒答（refused=True），硬答即失败
门槛：引用命中率 ≥0.95、拒答正确率 ≥0.9（设计文档 §7.2）。
用法：.venv/bin/python eval/scripts/run_citation_eval.py [--limit 20]
退出码：达标 0，未达标 1（需 LLM key 与 DB，本地跑）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT
from app.db import get_engine, init_db

GATE_CITE_HIT = 0.95
GATE_REFUSE = 0.90
EQUIV_COSINE = 0.80


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="rag_qa_citation.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟用）")
    args = ap.parse_args()

    from app.graphs.qa.graph import build_qa_graph

    init_db()
    engine = get_engine()
    path = PROJECT_ROOT / "eval/golden" / args.golden
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if args.limit:
        cases = cases[:args.limit]
    cite_cases = [c for c in cases if c["expect"] == "cite"]
    refuse_cases = [c for c in cases if c["expect"] == "refuse"]
    print(f"金标准：{len(cite_cases)} 引用题 + {len(refuse_cases)} 拒答题"
          f"（{args.golden}{'，limit=' + str(args.limit) if args.limit else ''}）")

    # 等价碎片扩展表（OCR 表格类语料同一答案散落多个碎片）
    with engine.connect() as conn:
        all_vecs = {r[0]: json.loads(r[1]) for r in conn.execute(
            sql_text("SELECT id, embedding::text FROM chunks")).all()}
    import numpy as np

    def expand(cid: str) -> set[str]:
        base = np.array(all_vecs.get(cid, []))
        if base.size == 0:
            return {cid}
        out = {cid}
        for other, vec in all_vecs.items():
            if other != cid and float(np.dot(base, np.array(vec)) /
                                      (np.linalg.norm(base) * np.linalg.norm(vec) + 1e-9)) >= EQUIV_COSINE:
                out.add(other)
        return out

    qa = build_qa_graph()
    cite_hit = refuse_ok = 0
    cite_refused = 0  # 引用题被拒答（可接受但计为未命中，单独观察）
    misses: list[str] = []
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        state = qa.invoke({
            "query": case["query"], "refused": False, "error": False,
            "rewrite_rounds": 0, "candidates": [], "cited_chunk_ids": [],
            "draft_answer": "", "final_answer": "",
        })
        cited = set(state.get("cited_chunk_ids", []))
        if case["expect"] == "cite":
            expected: set[str] = set()
            for cid in case["relevant_chunk_ids"]:
                expected |= expand(cid)
            if state.get("refused") or state.get("error"):
                cite_refused += 1
                misses.append(case["query"][:40])
            elif cited & expected:
                cite_hit += 1
            else:
                misses.append(case["query"][:40])
        else:
            if state.get("refused"):
                refuse_ok += 1
            else:
                misses.append(f"[硬答] {case['query'][:36]}")
        if i % 10 == 0:
            print(f"  …{i}/{len(cases)}", flush=True)

    cite_rate = cite_hit / len(cite_cases) if cite_cases else 1.0
    refuse_rate = refuse_ok / len(refuse_cases) if refuse_cases else 1.0
    elapsed = time.time() - t0
    print(f"\n引用命中率：{cite_hit}/{len(cite_cases)} = {cite_rate:.3f}"
          f"（门槛 ≥{GATE_CITE_HIT}；另有 {cite_refused} 条被拒答未计入命中）")
    print(f"拒答正确率：{refuse_ok}/{len(refuse_cases)} = {refuse_rate:.3f}"
          f"（门槛 ≥{GATE_REFUSE}）")
    print(f"平均耗时 {elapsed / max(len(cases), 1):.1f}s/条")
    if misses:
        print(f"未命中（前 8）：")
        for m in misses[:8]:
            print(f"  - {m}")

    if cite_rate >= GATE_CITE_HIT and refuse_rate >= GATE_REFUSE:
        print("✅ 达标")
        return 0
    print("❌ 未达标")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
