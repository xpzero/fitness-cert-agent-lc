#!/usr/bin/env python3
"""检索评测：Recall@5 / MRR@5（门槛 Recall@5 ≥ 0.75，设计文档 §7.2）。

用法：.venv/bin/python eval/scripts/run_retrieval_eval.py [--golden rag_qa_auto.jsonl]
退出码：达标 0，未达标 1（供 CI 使用）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import PROJECT_ROOT
from app.db import get_engine, init_db
from app.rag.search import searcher

GATE_RECALL_5 = 0.75


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="rag_qa_auto.jsonl")
    ap.add_argument("--no-hyde", action="store_true",
                    help="关闭 HyDE（CI 环境无 LLM key 时用；本地默认开启）")
    args = ap.parse_args()
    hyde = not args.no_hyde

    init_db()
    engine = get_engine()
    path = PROJECT_ROOT / "eval/golden" / args.golden
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    print(f"金标准：{len(cases)} 条（{args.golden}）")

    # 近似重复 chunk 并入相关集合：OCR 表格类语料同一答案散落多个碎片，
    # 只标采样 chunk 会把"检索到了等价碎片"误判为未命中。
    from sqlalchemy import text as sql_text

    with engine.connect() as conn:
        all_vecs = {r[0]: json.loads(r[1]) for r in conn.execute(
            sql_text("SELECT id, embedding::text FROM chunks")).all()}
    import numpy as np

    def expand_relevant(cid: str) -> set[str]:
        base = np.array(all_vecs[cid])
        out = {cid}
        for other, vec in all_vecs.items():
            if other != cid and float(np.dot(base, np.array(vec)) /
                                      (np.linalg.norm(base) * np.linalg.norm(vec) + 1e-9)) >= 0.80:
                out.add(other)
        return out

    hits5 = mrr = 0
    misses = []
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        candidates = searcher.search(case["query"], hyde=hyde)
        ids = [c.chunk_id for c in candidates[:5]]
        relevant = set().union(*(expand_relevant(cid) for cid in case["relevant_chunk_ids"]))
        rank = next((r for r, cid in enumerate(ids, 1) if cid in relevant), None)
        if rank:
            hits5 += 1
            mrr += 1 / rank
        else:
            misses.append({"query": case["query"], "expected": list(relevant),
                           "got_top3": [c.source_label for c in candidates[:3]]})
        if i % 10 == 0:
            print(f"  … {i}/{len(cases)}（running recall@5={hits5/i:.3f}）")

    n = len(cases)
    recall5, mrr5 = hits5 / n, mrr / n
    passed = recall5 >= GATE_RECALL_5
    report = (
        f"# 检索评测报告 {datetime.now().isoformat(timespec='seconds')}\n\n"
        f"| 指标 | 值 | 门槛 | 结果 |\n|---|---|---|---|\n"
        f"| Recall@5 | {recall5:.3f} | ≥{GATE_RECALL_5} | {'✅' if passed else '❌'} |\n"
        f"| MRR@5 | {mrr5:.3f} | - | |\n"
        f"| 样本 | {n} 条 auto | | |\n"
        f"| 平均耗时 | {time.time()-t0:.1f}s/条 {(time.time()-t0)/n:.2f}s | | |\n\n"
        f"## 未命中 case（{len(misses)}）\n\n" +
        "\n".join(f"- Q: {m['query']}\n  期望: {m['expected']}  实际top3: {m['got_top3']}"
                  for m in misses[:15])
    )
    report_path = PROJECT_ROOT / "eval/report/latest-retrieval.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    print(report.split("## 未命中")[0])
    print(f"报告 → {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
