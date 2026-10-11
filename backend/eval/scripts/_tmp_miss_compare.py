"""临时脚本：把检索评测未命中案例的期望块 vs 实际命中块原文并排打印（教学用）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text
from app.db import get_engine

MISSES = [
    ("做运动负荷测试的时候，出现哪些情况就必须马上停下来终止测试？",
     ["NSCA-CPT 官方备考题目 · P16", "ACSM 运动测试与处方指南 第9版（英文） · P111", "NSCA-CPT 2017 官方备考题目 · P16"]),
    ("实操考试是不是只考动作示范？听说还有体能测试，男生和女生的达标标准分别是什么？",
     ["美国体能协会体能训练概论（中文） · P150", "NSCA 战术体能训练参考指南（英文） · P250", "NSCA-CPT 私人教练认证指南 第2版（中文） · P291"]),
    ("第一次给新客户做咨询时，我直接问他身体情况和运动习惯然后开始定计划，这样是不是不太对？正确的咨询步骤应该怎么走？",
     ["NSCA-CPT 私人教练认证指南 第2版（中文） · P204", "ACE 学员手册 下（中文） · P360", "ACE 课程讲义 复习资料 · P31"]),
    ("会员让我多练卷腹想把肚子上的脂肪减掉，说练哪瘦哪，抗阻训练真的可以局部减脂吗？",
     ["ACSM 完整体适能健康指南（英文 2011） · P251", "ACE 学员手册 下（中文） · P63", "NSCA-CPT 2019 备考题 · P17"]),
    ("为什么刚开始做力量训练的那段时间，力量涨得挺明显，但肌肉围度却没怎么变大？",
     ["ACE 学员手册 下（中文） · P12", "NASM-CPT 私人教练认证指南 第6版（中文） · P308", "NSCA 培训 PPT：网球抗阻训练（英文） · P5"]),
]

golden = {}
for line in Path("eval/golden/rag_qa_auto.jsonl").read_text().splitlines():
    if line.strip():
        d = json.loads(line)
        golden[d["query"]] = d["relevant_chunk_ids"]


def fetch_chunks(ids):
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT ch.id, left(ch.content, 130), d.title, d.authority_level "
            "FROM chunks ch JOIN documents d ON ch.document_id = d.id "
            "WHERE ch.id = ANY(:ids)"), {"ids": ids}).all()
    return rows


def fetch_by_label(label):
    title, page = label.rsplit("·", 1)
    title, page = title.strip(), page.strip().lstrip("P").rstrip("?")
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT left(ch.content, 130), d.authority_level FROM chunks ch "
            "JOIN documents d ON ch.document_id = d.id "
            "WHERE d.title LIKE :t AND ch.page_no = :p LIMIT 1"),
            {"t": f"{title[:14]}%", "p": int(page)}).first()
    return row


for i, (q, got_labels) in enumerate(MISSES, 1):
    print(f"{'='*70}\n未命中 {i}: {q[:46]}")
    for cid, content, title, auth in fetch_chunks(golden[q]):
        print(f"  期望[{auth}] {title[:22]} · {cid[-8:]}: {content.replace(chr(10), ' ')}")
    for label in got_labels:
        row = fetch_by_label(label)
        if row:
            print(f"  实得[{row[1]}] {label[:34]}: {row[0].replace(chr(10), ' ')}")
