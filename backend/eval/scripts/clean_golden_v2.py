#!/usr/bin/env python3
"""金标准 v2 人工清洗（2026-11-10，依据 misses-detail.md 逐条判定）。

背景：auto 构建的金标准期望集 = seed chunk 的近重复扩展，只认 seed 所在
文档的知识簇。语料 135 份文档同知识高度冗余（同一考点在 NASM/ACE/NSCA/
ACSM 多本书都有正文），检索检回"别本书里同样正确的答案"被判 miss——
标签假阴性。bge-m3 之后 34 个 miss 逐条人工复核（query + seed 原文 +
实际 top5 原文三方对照），判定 26 条为假阴性、8 条为真缺口。

处理：
1. 26 条假阴性：把确实回答了问题的检回 chunk id 补进 relevant_chunk_ids
   （标签修正；近重复扩展在评测时自动带上其重复簇）
2. 8 条真缺口保留 miss 不动（M3/M4/M7/M13/M18/M20/M26/M34——细节型数字
   题、拼接错题、同章不同节，是改写增强的真实靶子）
3. 期望集全灭（chunk 已被重解析删除）的 8 条整条剔除（120→112，
   与 build_golden v2 清洗口径一致）

用法：.venv/bin/python eval/scripts/clean_golden_v2.py   （幂等：重复跑无新增）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT
from app.db import get_engine, init_db

# 假阴性修正表：query 前缀 → 确认回答了问题的检回 chunk id（出处见上方判定）
CORRECTIONS: dict[str, list[str]] = {
    "教练，我想问一下，四足臂/对侧腿抬起": ["doc-bb6ed177f7-1083", "doc-0f9887767e-1966"],  # NASM OPT P330 动作完整做法 / ACSM P328 Quadruped
    "教练，我脚踝扭伤": ["doc-087f6a28db-1155", "doc-cdbe6625f2-590"],  # 扭伤恢复训练指导（本体感受/力量修复）
    "教练，我是一名马拉松运动员": ["doc-de4aa7becf-271", "doc-de4aa7becf-312"],  # 每搏输出量增加→最大心输出量（原题答案）
    "教练，训练的时候万一出意外": ["doc-cdbe6625f2-710", "doc-cdbe6625f2-716"],  # 弃权声明书保护法律责任 / 监督不离客户
    "教练，我练功能训练的时候": ["doc-ca5d84cf87-389", "doc-ca5d84cf87-392"],  # 功能性动作筛查方案与观察要点
    "教练，我复习到增强训练": ["doc-68c48e2bca-201", "doc-fc5e4b5a2c-120"],  # 增强式训练系统设计顺序 / 频率与组间歇注意
    "在无氧训练中，收缩压和舒张压": ["doc-de4aa7becf-268"],  # 急性无氧运动血压显著增加
    "教练，根据这个教材，哪种弯举练习": ["doc-7864e15b7d-629", "doc-9b61890370-1135", "doc-e187bd9eb8-2304"],  # 肱二头肌弯举练习清单/锤式弯举
    "教练，根据教材内容，我想问一下，稳定作用": ["doc-bb6ed177f7-495", "doc-7864e15b7d-480"],  # 等长=稳定概念 / 缓冲阶段定义
    "教练，我最近膝盖有点疼": ["doc-cdbe6625f2-582", "doc-af7e80ab2e-1479"],  # 跑步膝=PFPS 症状与处理
    "超级组训练法": ["doc-ea9f0b0415-250", "doc-bb6ed177f7-1322"],  # 超级组具体例子（弯举+三头下压）/ 定义
    "教练，我每次刚开始健身的时候都很有热情": ["doc-9b61890370-1027", "doc-9b61890370-1056"],  # 放弃因素预测 / 积极想法与精神准备
    "教练，刚开始做抗阻训练的时候": ["doc-5d520d6951-531", "doc-e04cbb77a4-196"],  # 初学者 1-2 组打基础再进阶
    "教练，我在准备健身教练考试，看到教材里提到了体能评估": ["doc-1746f9d30f-2062", "doc-9b61890370-207"],  # 体能评估组成清单
    "教练，我在准备考试，看到教材里提到了癌症患者": ["doc-cdbe6625f2-493", "doc-9b0060466b-680"],  # 癌症患者运动指南
    "教练，我带一个体重比较大的客户": ["doc-af7e80ab2e-1345", "doc-9b61890370-776"],  # 超重客户处方关注事项
    "教练，慢性病患者在运动时": ["doc-087f6a28db-926", "doc-1ca2993fb2-3016"],  # 慢性病客户筛查与转诊
    "教练，我准备开始健身计划了，请问如果我有骨质疏松": ["doc-af7e80ab2e-318", "doc-43879ed45b-1077"],  # 疾病状态营养转诊（原题答案）
    "教练，在客户家里训练的时候": ["doc-087f6a28db-1237", "doc-ccf10735ab-1459"],  # 家庭训练音乐版权（原题出处）
    "教练，我在做肌肉训练评估的时候，怎么判断一个动作是不是标准姿势": ["doc-087f6a28db-640", "doc-ca5d84cf87-371"],  # 直角规则姿势评估
    "教练，我想问一下，做双腿背桥": ["doc-9b61890370-425", "doc-0f9887767e-1964"],  # 臀桥技术要领（不过伸/骨盆中立）
    "教练，我在准备健身教练考试，看到教材里提到各个生命阶段": ["doc-087f6a28db-1070", "doc-af7e80ab2e-1233", "doc-9b61890370-776"],  # 老年人计划注意事项
    "教练，我想知道怎么提高爆发力": ["doc-af7e80ab2e-934", "doc-219f04601e-131"],  # 爆发力训练顺序 / 负荷策略
    "教练，我有点疝气": ["doc-ab03076c0e-1421", "doc-ab03076c0e-1422", "doc-9b0060466b-688"],  # 举重疝气风险需医学许可
    "教练，我在训练的时候，有时候会感觉关节特别响": ["doc-cdbe6625f2-556"],  # 关节弹响/无力/锁定症状解读
    "教练，我在准备考试，看到教材里提到了关于责任和法律术语": ["doc-b406152202-3448", "doc-e187bd9eb8-3694", "doc-de4aa7becf-1351"],  # 力量训练法律责任
}


def main() -> None:
    init_db()
    with get_engine().connect() as conn:
        live_ids = {r[0] for r in conn.execute(sql_text("SELECT id FROM chunks")).all()}

    path = PROJECT_ROOT / "eval/golden/rag_qa_v2.jsonl"
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    corrected = dead_removed = invalid_ids = 0

    kept = []
    for case in cases:
        # 剔除期望集全灭（chunk 已不存在——文档重解析后 id 漂移）
        if not [c for c in case["relevant_chunk_ids"] if c in live_ids]:
            dead_removed += 1
            continue
        for prefix, adds in CORRECTIONS.items():
            if case["query"].startswith(prefix):
                new = [c for c in adds if c in live_ids and c not in case["relevant_chunk_ids"]]
                invalid_ids += len([c for c in adds if c not in live_ids])
                if new:
                    case["relevant_chunk_ids"] += new
                    corrected += 1
        kept.append(case)

    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in kept) + "\n")
    print(f"清洗完成：标签修正 {corrected} 条 / 剔除全灭 {dead_removed} 条 / "
          f"无效补入 id {invalid_ids} 个（已存在的不重复计） → 共 {len(kept)} 条")


if __name__ == "__main__":
    main()
