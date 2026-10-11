#!/usr/bin/env python3
"""构建引用正确率金标准（W7）：90 条引用题（LLM 从 chunk 生成问题）+ 10 条应拒答。

输出 eval/golden/rag_qa_citation.jsonl：
{query, relevant_chunk_ids, expect: "cite" | "refuse"}
- cite 类：期望回答引用 relevant_chunk_ids（或其等价碎片，评测端按余弦 ≥0.80 扩展）
- refuse 类：与健身考证无关的域外问题，期望 qa 子图拒答而非硬答

auto 属性与 rag_qa_auto.jsonl 同语义：测"引用一致性"（答案是否长在出处上），
正式人工核版在 eval/report/ 记录抽检结论。
用法：.venv/bin/python eval/scripts/build_citation_golden.py [--n 90]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text

from app.llm import llm_client
from app.config import PROJECT_ROOT
from app.db import get_engine, init_db

MIN_LEN = 150
SEED = 2026

REFUSAL_QUERIES = [
    "今天股市行情怎么样？适合加仓吗？",
    "帮我写一首关于秋天的现代诗，要押韵。",
    "Python 里怎么把一个列表去重？",
    "推荐几部最近好看的悬疑电影。",
    "红烧肉怎么做才不腻？",
    "明天天气适合去爬山吗？",
    "帮我订一张明天去上海的高铁票。",
    "宇宙的年龄大约是多少？",
    "英语四级考试什么时候报名？",
    "最近有什么明星八卦吗？",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=90)
    args = ap.parse_args()

    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.id, c.content FROM chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "WHERE length(c.content) >= :min_len ORDER BY c.id"
        ), {"min_len": MIN_LEN}).all()

    random.seed(SEED)
    sampled = random.sample([tuple(r) for r in rows], min(args.n, len(rows)))
    print(f"可用 chunk {len(rows)}，采样 {len(sampled)} 条生成引用题")

    out_path = PROJECT_ROOT / "eval/golden/rag_qa_citation.jsonl"
    ok = fail = 0
    with out_path.open("w", encoding="utf-8") as f:
        for cid, content in sampled:
            try:
                q = llm_client.chat_json([
                    {"role": "system",
                     "content": "你是健身教练考证考生。根据给定教材片段，提出一个考生真实会问的、"
                                "能从该片段找到答案的问题。只输出 JSON：{\"question\": \"...\"}。"
                                "不要照抄原文句子，用自然口语提问。"},
                    {"role": "user", "content": content[:800]},
                ], model_tier="gen", temperature=0.5).get("question", "").strip()
                if q:
                    f.write(json.dumps({"query": q, "relevant_chunk_ids": [cid],
                                        "expect": "cite"}, ensure_ascii=False) + "\n")
                    ok += 1
                else:
                    fail += 1
            except Exception as e:  # noqa: BLE001
                print(f"skip {cid}: {str(e)[:60]}")
                fail += 1
        for q in REFUSAL_QUERIES:
            f.write(json.dumps({"query": q, "relevant_chunk_ids": [],
                                "expect": "refuse"}, ensure_ascii=False) + "\n")
    print(f"引用金标准：{ok} 条引用题 + {len(REFUSAL_QUERIES)} 条拒答题"
          f"（{fail} 条生成失败）→ {out_path}")


if __name__ == "__main__":
    main()
