#!/usr/bin/env python3
"""意图路由评测（W5，设计文档 P3 遗留验收：路由准确率 ≥0.92）。

走生产同款路径 supervisor.classify_intent（规则快路径 + chat_fast LLM 路由），
对 eval/golden/intent_labeled.jsonl 逐条比对。分类别报告准确率。
用法：.venv/bin/python eval/scripts/run_intent_eval.py
退出码：达标 0，未达标 1（需 LLM key）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import PROJECT_ROOT  # noqa: E402
from app.graphs.supervisor import classify_intent  # noqa: E402

GATE_ACCURACY = 0.92


def main() -> int:
    path = PROJECT_ROOT / "eval/golden/intent_labeled.jsonl"
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    print(f"意图标注集：{len(cases)} 条")

    correct = 0
    by_intent: dict[str, dict] = {}
    errors: list[str] = []
    for c in cases:
        out = classify_intent({"messages": [{"role": "user", "content": c["text"]}],
                               "user_id": "eval"})
        got = out["intent"]
        stat = by_intent.setdefault(c["expect"], {"n": 0, "ok": 0})
        stat["n"] += 1
        if got == c["expect"]:
            correct += 1
            stat["ok"] += 1
        else:
            errors.append(f"[{c['expect']}→{got}] {c['text'][:36]}")

    accuracy = correct / len(cases) if cases else 0.0
    print(f"\n{'意图':<12}{'正确/总数':<14}准确率")
    for intent in sorted(by_intent):
        s = by_intent[intent]
        print(f"{intent:<12}{s['ok']:>4}/{s['n']:<8}{s['ok'] / s['n']:.2f}")
    print(f"\n总体准确率：{accuracy:.3f}（门槛 ≥{GATE_ACCURACY}）")
    if errors:
        print("错例（前 10）：")
        for e in errors[:10]:
            print(f"  {e}")

    if accuracy >= GATE_ACCURACY:
        print("✅ 达标")
        return 0
    print("❌ 未达标")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
