#!/usr/bin/env python3
"""语料入库：考点树 YAML → exam_points；markdown（带 [[P页码]] 标记）→ chunk → embedding → pgvector。

语料写库统一走 app/rag/pipeline 的 ingest.ingest_markdown（与知识库上传同一条路径：
幂等覆盖、跨语言摘要、embedding）。本脚本只负责考点种子与语料清单。
用法：.venv/bin/python scripts/ingest.py（重复执行安全：按 document_id 幂等覆盖）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from sqlalchemy import text

from app.config import PROJECT_ROOT, settings
from app.db import get_engine, init_db
from app.models.tables import ExamPoint
from app.rag.pipeline import doc_id_from_title, ingest

# 语料清单：路径 / 标题 / 类型 / 权威级（1官方 2半官方 3补充）
CORPUS = [
    # 来源为 ACE-CPT-Notes / EES 等四大证开源笔记的整理汇总（原国职时期的抓取产物，
    # 内容与四大证方向天然契合，故保留为种子语料；文件名已去国职化）。
    dict(path="knowledge/processed/四大证CPT核心知识点.md",
         title="四大证 CPT 核心知识点（ACE/EES 开源笔记整理）",
         source_type="笔记", authority_level=3,
         start_marker="## 第一章"),
    # 用户找到的四大证资料：经「知识库」tab 上传（uploads/ → 自动解析入库）
]

SYLLABUS = "knowledge/syllabus/nsca_cpt.yaml"


def load_exam_points(engine) -> int:
    """考点树 YAML → exam_points 表（幂等覆盖）。"""
    data = yaml.safe_load((PROJECT_ROOT / SYLLABUS).read_text())
    rows = []
    for section, key in (("theory", "T"), ("practice", "P")):
        for chap in data.get(section, []):
            rows.append(dict(id=chap["id"], cert_id=data["cert"], parent_id="",
                             chapter=chap["chapter"], title=chap["chapter"]))
            for p in chap["points"]:
                rows.append(dict(id=p["id"], cert_id=data["cert"], parent_id=chap["id"],
                                 chapter=chap["chapter"], title=p["title"]))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM exam_points WHERE cert_id = :c"),
                     {"c": data["cert"]})
        conn.execute(ExamPoint.__table__.insert(), rows)
    return len(rows)


def ingest_file(item: dict) -> int:
    """单份语料 → ingest_markdown（幂等：同 doc_id 先清旧再插）。返回 chunk 数。"""
    md = (PROJECT_ROOT / item["path"]).read_text()
    if item.get("start_marker") and item["start_marker"] in md:
        md = md[md.index(item["start_marker"]):]  # 跳过元信息/目录等非知识前缀
    return ingest.ingest_markdown(doc_id=doc_id_from_title(item["title"]),
                           title=item["title"], markdown_text=md,
                           authority_level=item["authority_level"],
                           source_type=item["source_type"])


def main() -> None:
    init_db()
    n_points = load_exam_points(get_engine())
    print(f"exam_points: {n_points} 条（{settings.default_cert}）")
    total = 0
    for item in CORPUS:
        n = ingest_file(item)
        total += n
        print(f"[ok] {item['title'][:30]}… → {n} chunks（authority {item['authority_level']}）")
    print(f"完成：{total} chunks 入库")


if __name__ == "__main__":
    main()
