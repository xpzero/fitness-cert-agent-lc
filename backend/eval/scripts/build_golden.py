#!/usr/bin/env python3
"""自动构建检索金标准集：从库内 chunk 采样，LLM 生成"考生会问的问题"。

输出 eval/golden/rag_qa_auto.jsonl：{query, relevant_chunk_ids, auto: true}
注意：auto 金标准测的是"检索一致性"（能否找回出处），不是人工标注的语义金标准；
上线前的人工金标准（rag_qa.jsonl）另行构建。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text

from app.llm import llm_client
from app.config import PROJECT_ROOT, settings
from app.db import get_engine, init_db

N_SAMPLES = 40
MIN_LEN = 150
SEED = 42


def main() -> None:
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.id, c.content FROM chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "WHERE length(c.content) >= :min_len ORDER BY c.id"
        ), {"min_len": MIN_LEN}).all()

    random.seed(SEED)
    sampled = random.sample([tuple(r) for r in rows], min(N_SAMPLES, len(rows)))

    out_path = PROJECT_ROOT / "eval/golden/rag_qa_auto.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    with out_path.open("w", encoding="utf-8") as f:
        for cid, content in sampled:
            try:
                raw = llm_client.chat_gen([
                    {"role": "system",
                     "content": "你是健身教练考证考生。根据给定教材片段，提出一个考生真实会问的、"
                                "能从该片段找到答案的问题。只输出 JSON：{\"question\": \"...\"}。"
                                "不要照抄原文句子，用自然口语提问。"},
                    {"role": "user", "content": content[:800]},
                ], temperature=0.5, response_format_json=True)
                q = json.loads(raw).get("question", "").strip()
                if q:
                    f.write(json.dumps({"query": q, "relevant_chunk_ids": [cid],
                                        "auto": True}, ensure_ascii=False) + "\n")
                    ok += 1
                else:
                    fail += 1
            except Exception as e:  # noqa: BLE001
                print(f"skip {cid}: {str(e)[:60]}")
                fail += 1
    print(f"金标准生成：{ok} 条成功，{fail} 条失败 → {out_path}")


if __name__ == "__main__":
    main()
