#!/usr/bin/env python3
"""批量出题铺覆盖：循环跑 quizgen 直到覆盖目标或轮次上限。

用法：.venv/bin/python scripts/batch_generate.py [--target 24] [--rounds 10]
每轮 4 个考点；重复失败的考点自动进入排除名单。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db import init_db
from app.services.repositories import repo

CERT = settings.default_cert
from app.graphs.quizgen.graph import build_quizgen_graph  # noqa: E402


def coverage(cert: str) -> tuple[int, int, list[str]]:
    counts = repo.exam_point_counts(cert)
    covered = sum(1 for r in counts if r["n"])
    return covered, len(counts), [r["id"] for r in counts if not r["n"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=24, help="覆盖考点数目标")
    ap.add_argument("--rounds", type=int, default=10)
    args = ap.parse_args()

    init_db()
    g = build_quizgen_graph()
    exclude: list[str] = []

    for rnd in range(1, args.rounds + 1):
        cov, total, uncovered = coverage(CERT)
        print(f"—— 第 {rnd} 轮（覆盖 {cov}/{total}，未覆盖 {len(uncovered)}）——", flush=True)
        if cov >= args.target or not uncovered:
            print("达标或无剩余考点，结束。")
            break
        state = g.invoke({"cert_id": CERT, "n_points": 4,
                          "exclude_points": exclude})
        for d in state["accepted"]:
            print(f"  ✅ [{d.question_type}] {d.stem[:36]} | "
                  f"g={d.grounding_score} q={d.quality_score}",
                  flush=True)
        for r in state["rejected"]:
            print(f"  ❌ {r['stem'][:30]} | {r['reason']}", flush=True)
        if not state["coverage_delta"]:
            # 本轮零覆盖：把本轮选中的考点加入排除，避免死循环
            exclude += [p["id"] for p in state["exam_points"]
                        if p["id"] not in state["coverage_delta"]]
        time.sleep(2)
    cov, total, uncovered = coverage(CERT)
    print(f"最终覆盖：{cov}/{total} 考点；未覆盖：{uncovered}")


if __name__ == "__main__":
    main()
