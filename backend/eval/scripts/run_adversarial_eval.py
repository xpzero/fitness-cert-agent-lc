#!/usr/bin/env python3
"""对抗评审评测：坏题捕获率 / 好题误伤率（门槛 捕获 ≥0.70、误伤 ≤0.20）。

用法：.venv/bin/python eval/scripts/run_adversarial_eval.py [--cases adversarial_cases.jsonl]
注入用例不经生成与前三道闸，直接构造 QuestionDraft 喂 AdversarialGate（被测单元），
同时输出 rubric-only 基线（QualityGate 对同一批题的打分拦截情况）作对比——
两者的差距即"对抗评审相对于打分的增量"。
退出码：达标 0，未达标 1（供 CI 使用；需 LLM key，本地跑）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import PROJECT_ROOT  # noqa: E402
from app.graphs.quizgen.graph import (  # noqa: E402
    AdversarialGate,
    QualityGate,
    QuestionDraft,
)

GATE_CAPTURE_MIN = 0.70     # 坏题（ambiguous/guessable）拦截率下限
GATE_FALSE_REJECT_MAX = 0.20  # 好题（good）误拒率上限


def to_draft(case: dict) -> QuestionDraft:
    return QuestionDraft(
        point_id=case["id"], point_title=case["kind"],
        question_type=case.get("type", "single"), stem=case["stem"],
        options=case["options"], answer=case["answer"],
        explanation=case.get("explanation", ""),
        evidence_text=case.get("evidence_text", ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="adversarial_cases.jsonl")
    args = ap.parse_args()

    path = PROJECT_ROOT / "eval/golden" / args.cases
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    drafts = [to_draft(c) for c in cases]
    print(f"注入用例：{len(cases)} 条（{args.cases}）")

    # 被测单元：对抗闸（insert=False，判定不写库；engine 不触达）
    _, adv_rejected = AdversarialGate(None).filter(drafts, "eval", insert=False)
    adv_rej_ids = {r["stem"][:60] for r in adv_rejected}

    # rubric 基线：QualityGate 打分（W2 起只打分不插库，无需 engine）
    _, rubric_rejected = QualityGate(None).filter(
        [to_draft(c) for c in cases], "eval")
    rubric_rej_ids = {r["stem"][:60] for r in rubric_rejected}

    def rate(rej_ids, kind):
        sub = [c for c in cases if c["kind"] == kind]
        hit = sum(1 for c in sub if c["stem"][:60] in rej_ids)
        return hit, len(sub)

    rows = []
    for kind, label in (("ambiguous", "歧义题"), ("guessable", "可猜测题"),
                        ("good", "合格题")):
        adv_hit, n = rate(adv_rej_ids, kind)
        rub_hit, _ = rate(rubric_rej_ids, kind)
        rows.append((kind, label, adv_hit, rub_hit, n))

    print(f"\n{'类别':<10}{'对抗拦截':>10}{'rubric拦截':>12}{'总数':>8}")
    for kind, label, adv_hit, rub_hit, n in rows:
        print(f"{label:<10}{adv_hit:>8}/{n}{rub_hit:>10}/{n}{n:>8}")

    bad = [r for r in rows if r[0] in ("ambiguous", "guessable")]
    capture = (sum(r[2] for r in bad) / sum(r[4] for r in bad)) if bad else 1.0
    rubric_capture = (sum(r[3] for r in bad) / sum(r[4] for r in bad)) if bad else 0.0
    good_row = next(r for r in rows if r[0] == "good")
    false_reject = good_row[2] / good_row[4] if good_row[4] else 0.0
    rubric_false = good_row[3] / good_row[4] if good_row[4] else 0.0

    print(f"\n捕获率（坏题）：对抗 {capture:.2f} vs rubric {rubric_capture:.2f}"
          f"（门槛 ≥{GATE_CAPTURE_MIN}）")
    print(f"误伤率（好题）：对抗 {false_reject:.2f} vs rubric {rubric_false:.2f}"
          f"（门槛 ≤{GATE_FALSE_REJECT_MAX}）")

    if capture >= GATE_CAPTURE_MIN and false_reject <= GATE_FALSE_REJECT_MAX:
        print("✅ 达标")
        return 0
    print("❌ 未达标")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
