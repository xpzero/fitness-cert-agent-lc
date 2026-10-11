#!/usr/bin/env python3
"""导出人工抽检清单：verified 题目 + 逐字依据 → markdown，供人工审题。

用法：.venv/bin/python eval/scripts/export_review.py
P2 门槛：抽检准确率 ≥ 97%（设计文档 §8）。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT
from app.db import get_engine


def main() -> None:
    engine = get_engine()
    rows = engine.connect().execute(sql_text(
        "SELECT id, type, stem, answer, options::text AS options, evidence_text, "
        "quality_score FROM questions WHERE verified ORDER BY id"
    )).mappings().all()

    lines = [
        "# 人工抽检清单 — 出题准确率验收（P2 门槛 ≥97%）",
        "",
        f"> 生成时间：{date.today()}　已入库 verified 题目：**{len(rows)} 道**",
        "> 审查要点：① 题干表述清晰无歧义；② 答案唯一且正确；"
        "③ evidence_text 是否真在语料中且能推出答案。",
        "> 每题末尾勾选：通过 / 不通过（不通过的写原因，用于 prompt 迭代）。",
        "",
    ]
    for i, q in enumerate(rows, 1):
        opts = json.loads(q["options"] or "{}")
        lines += [
            f"## 第 {i} 题　`{q['id']}`　{q['type']}　质量分 {q['quality_score']}",
            "",
            f"**题干**：{q['stem']}",
        ]
        for k in sorted(opts):
            lines.append(f"- {k}. {opts[k]}")
        lines += [
            f"**答案**：`{q['answer']}`",
            f"**逐字依据**：{q['evidence_text']}",
            "",
            "- [ ] 通过　- [ ] 不通过：________",
            "",
        ]
    out = PROJECT_ROOT / "eval/report/人工抽检清单.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"抽检清单：{len(rows)} 题 → {out}")


if __name__ == "__main__":
    main()
