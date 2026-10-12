"""子图D：刷题/模考（确定性判分 + 薄弱点诊断 + SM-2 + 讲题，设计文档 §4.4）——P2 实现。

两段式 API 流（表单交互不适合走单次图执行）：
- start_questions(): 选题（练习/错题复习/模考），返回无答案题目给前端
- grade_submission(): 交卷后确定性判分 → 薄弱点诊断 → 讲题（仅错题）→ SM-2 排程 → 报告
"""
from __future__ import annotations

import json
import math
from datetime import date
from typing import TypedDict

from sqlalchemy import text as sql_text

from app.llm import llm_client
from app.db import get_engine

# 四大证笔试规格（题量，均为四选一单选；2026-10 核实的公开考试信息）
MOCK_SPECS = {"nsca_cpt": 155, "ace_cpt": 150, "acsm_cpt": 150, "nasm_cpt": 120}
MOCK_MAX = 160  # 抽题上限（防误配超大规格)
from app.prompts.practice import EXPLAIN_SYSTEM
from app.services.repositories import repo
from app.tools.grader import grade, resolve_answer_key
from app.tools.sm2 import Sm2Record, new_record, review

PASS_LINE = 60  # 官方 60 分及格


class PracticeState(TypedDict):
    user_id: str
    mode: str                  # practice | mock | wrong_review | favorites
    cert_id: str
    count: int
    questions: list[dict]
    answers: list[dict]
    results: list[dict]
    weak_points: list[dict]
    explanations: list[dict]
    scheduled_count: int
    report: dict


# ---------------------------------------------------------------- 选题

def start_questions(user_id: str, mode: str, cert_id: str = "",
                    count: int = 5) -> list[dict]:
    """选题并返回题面（刻意不含 answer/explanation——防前端泄露答案）。

    四种模式对应不同题源：
    practice/mock 随机抽 verified 题（mock 上限放宽到 100 题）；
    wrong_review 取错题本中今日到期者（SM-2 排程驱动）；
    favorites 取收藏夹最近 20 题。
    """
    from app.config import settings

    engine = get_engine()
    cert_id = cert_id or settings.default_cert
    count = max(1, min(int(count), 20 if mode != "mock" else 100))
    if mode == "wrong_review":
        with engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT q.id, q.type, q.stem, q.options::text AS options
                FROM wrong_book w JOIN questions q ON q.id = w.question_id
                WHERE w.user_id = :u AND w.due_date <= :today AND q.verified
                ORDER BY w.due_date LIMIT 20
            """), {"u": user_id, "today": date.today()}).mappings().all()
    elif mode == "favorites":
        with engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT q.id, q.type, q.stem, q.options::text AS options
                FROM favorites f JOIN questions q ON q.id = f.question_id
                WHERE f.user_id = :u AND q.verified
                ORDER BY f.created_at DESC LIMIT 20
            """), {"u": user_id}).mappings().all()
    elif mode == "mock":
        # 全真模考：按证书规格抽题——四大证笔试均为四选一单选，数量取考试规格；
        # 题库不足时按可用题量等比缩放出示意卷
        spec_n = MOCK_SPECS.get(cert_id, 0) or count
        with engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT id, type, stem, options::text AS options FROM questions
                WHERE cert_id = :c AND verified AND type = 'single'
                ORDER BY random() LIMIT :n
            """), {"c": cert_id, "n": min(spec_n, MOCK_MAX)}).mappings().all()
    else:
        with engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT id, type, stem, options::text AS options FROM questions
                WHERE cert_id = :c AND verified
                ORDER BY random() LIMIT :n
            """), {"c": cert_id, "n": count}).mappings().all()
    return [dict(r, options=json.loads(r["options"] or "{}")) for r in rows]


# ---------------------------------------------------------------- 交卷链路

def _grade_answers(state: PracticeState) -> dict:
    """逐题确定性判分（tools.grader，零 LLM）。history_by_question 取该题的
    历史答题统计（答过/答对次数），随结果一起返回供前端展示掌握度。"""
    engine = get_engine()
    with engine.connect() as conn:
        history_by_question = {r[0]: (r[1], r[2]) for r in conn.execute(sql_text("""
            SELECT question_id, count(*), count(*) FILTER (WHERE is_correct)
            FROM user_answers WHERE question_id = ANY(:ids) GROUP BY question_id
        """), {"ids": [a["question_id"] for a in state["answers"]]}).all()}
    results = []
    questions_by_id = {q["id"]: q for q in state["questions"]}
    for submission in state["answers"]:
        question = questions_by_id.get(submission["question_id"])
        if not question:
            continue
        # 标准答案归一到选项字母：判断题存量数据存的是「对/错」文字，
        # 前端提交/高亮都用字母键，不映射则永远判错
        answer_key = resolve_answer_key(question["answer"],
                                        question.get("options") or {})
        graded = grade(question["type"], submission.get("answer", ""), answer_key)
        results.append({"question_id": question["id"], "type": question["type"],
                        "stem": question["stem"],
                        "user_answer": submission.get("answer", ""),
                        "correct_answer": answer_key,
                        "correct": graded.is_correct, "detail": graded.detail,
                        "explanation": question.get("explanation", ""),
                        "source_chunk_ids": question.get("source_chunk_ids", []),
                        "exam_point_ids": question.get("exam_point_ids", []),
                        "history": history_by_question.get(question["id"],
                                                           (0, 0))})  # (答过, 答对)
    return {"results": results}


def _diagnose_weak_points(state: PracticeState) -> dict:
    """薄弱点诊断：按章节聚合正确率，取"有过错且正确率最低"的前 3 章。

    一题可挂多个考点，此处按其（最后一个命中的）考点所属章节归组——
    诊断粒度到章即可支撑"补哪一章"的建议。
    """
    engine = get_engine()
    chapter_stats: dict[str, dict] = {}
    with engine.connect() as conn:
        for r in state["results"]:
            point_row = None
            for pid in r["exam_point_ids"]:
                point_row = conn.execute(sql_text(
                    "SELECT chapter, title FROM exam_points WHERE id = :i"),
                    {"i": pid}).first()
            key = point_row[0] if point_row else "未分类"
            agg = chapter_stats.setdefault(key, {"chapter": key, "total": 0,
                                                 "correct": 0})
            agg["total"] += 1
            agg["correct"] += int(r["correct"])
    weak_rows = sorted((v for v in chapter_stats.values() if v["correct"] < v["total"]),
                       key=lambda v: v["correct"] / v["total"])[:3]
    return {"weak_points": weak_rows}


def _explain_wrong(state: PracticeState) -> dict:
    """错题讲题：引 source_chunk_ids 的原文，溯源式讲解（最多 5 题，控延迟）。"""
    explanation_rows = []
    wrong_results = [r for r in state["results"] if not r["correct"]][:5]
    # 批量取讲题所需 chunk（单查询，消除逐题逐 chunk 的 N+1）
    contents = repo.chunks_by_ids(
        [cid for r in wrong_results for cid in r["source_chunk_ids"][:2]])
    for r in wrong_results:
        # 材料标签用「文档名 · 页码」——用 chunk id 会被 LLM 原样抄进讲解，
        # 用户看到的就是一串 doc-xxxx 哈希
        blocks = [f"[{contents[cid].title} · P{contents[cid].page_no}] "
                  f"{contents[cid].content[:400]}"
                  for cid in r["source_chunk_ids"][:2] if cid in contents]
        if blocks:
            try:
                explanation_text = llm_client.chat_gen([
                    {"role": "system", "content": EXPLAIN_SYSTEM},
                    {"role": "user",
                     "content": f"题目：{r['stem']}\n正确答案：{r['correct_answer']}\n"
                                f"考生答案：{r['user_answer'] or '（未作答）'}\n\n教材原文：\n"
                                + "\n".join(blocks)},
                ], max_tokens=500)
            except Exception as e:  # noqa: BLE001
                explanation_text = f"（讲题服务暂不可用：{str(e)[:80]}）"
        else:
            explanation_text = r.get("explanation", "") or "（暂无讲解）"
        explanation_rows.append({"question_id": r["question_id"],
                                 "explain": explanation_text})
    return {"explanations": explanation_rows}


def _schedule_reviews(state: PracticeState) -> dict:
    """错题入 wrong_book 并按 SM-2 排程；错题本内的题答对则推进间隔。

    新错题先 review(new_record, correct=False) 走一遍答错分支：
    得到 ease 降罚后的次日到期排程（而非直接存初始值）。
    最后把本次作答全部写入 user_answers（掌握度/连续打卡的数据源）。
    """
    engine = get_engine()
    scheduled_count = 0
    today = date.today()
    with engine.begin() as conn:
        for r in state["results"]:
            existing_sm2_row = conn.execute(sql_text(
                "SELECT ease, interval_days, reps FROM wrong_book "
                "WHERE user_id = :u AND question_id = :q"),
                {"u": state["user_id"], "q": r["question_id"]}).first()
            if not r["correct"] and not existing_sm2_row:
                # 答错且不在错题本 → 新建记录（ON CONFLICT 兜底并发重复）
                rec = review(new_record(today), False, today)
                conn.execute(sql_text("""
                    INSERT INTO wrong_book (user_id, question_id, ease, interval_days, reps, due_date)
                    VALUES (:u, :q, :ease, :interval, :reps, :due)
                    ON CONFLICT (user_id, question_id) DO NOTHING
                """), {"u": state["user_id"], "q": r["question_id"], "ease": rec.ease,
                       "interval": rec.interval_days, "reps": rec.reps, "due": rec.due_date})
                scheduled_count += 1
            elif existing_sm2_row:
                # 已在错题本：无论对错都按 SM-2 更新（对→间隔拉长，错→重置）
                rec = review(Sm2Record.from_fields(existing_sm2_row[0],
                                                   existing_sm2_row[1],
                                                   existing_sm2_row[2], today),
                             r["correct"], today)
                conn.execute(sql_text("""
                    UPDATE wrong_book SET ease = :ease, interval_days = :interval,
                           reps = :reps, due_date = :due
                    WHERE user_id = :u AND question_id = :q
                """), {"u": state["user_id"], "q": r["question_id"], "ease": rec.ease,
                       "interval": rec.interval_days, "reps": rec.reps, "due": rec.due_date})
                scheduled_count += 1
    # 记录答题历史
    with engine.begin() as conn:
        for submission, result in zip(state["answers"], state["results"]):
            conn.execute(sql_text("""
                INSERT INTO user_answers (user_id, question_id, answer, is_correct)
                VALUES (:u, :q, :a, :c)
            """), {"u": state["user_id"], "q": result["question_id"],
                   "a": submission.get("answer", ""), "c": result["correct"]})
    return {"scheduled_count": scheduled_count}


def _build_report(state: PracticeState) -> dict:
    results = state["results"]
    total = len(results)
    score = round(sum(1.0 for r in results if r["correct"]) * 100 / total, 1) if total else 0.0
    stats_by_point_id: dict[str, dict] = {}
    for r in results:
        for pid in r["exam_point_ids"]:
            stats_by_point_id.setdefault(pid, {"correct": 0, "total": 0})
            stats_by_point_id[pid]["total"] += 1
            stats_by_point_id[pid]["correct"] += int(r["correct"])
    if state["mode"] == "mock":
        engine = get_engine()
        # 通过概率：以及格线为中心的 sigmoid（8 分带宽）——把分数折算成
        # 直观的 0~1 概率供参考，不做真实通过率预测
        pass_probability = 1 / (1 + math.exp(-(score - PASS_LINE) / 8))
        report = {"mode": "mock", "total": total, "score": score,
                  "pass_line": PASS_LINE,
                  "pass_probability": round(pass_probability, 3),
                  "verdict": "预计通过线以上" if score >= PASS_LINE else "低于及格线，按薄弱点加练",
                  "per_question": {k: v for k, v in stats_by_point_id.items()}}
        with engine.begin() as conn:
            conn.execute(sql_text("""
                INSERT INTO mock_reports (user_id, score, pass_probability, total)
                VALUES (:u, :s, :p, :t)
            """), {"u": state["user_id"], "s": score, "p": pass_probability,
                   "t": total})
        # 跨子图联动：模考成绩自动触发规划调整（practice → planning）
        try:
            from app.graphs.planning.graph import auto_adjust_from_mock

            adjustment = auto_adjust_from_mock(state["user_id"], score,
                                               state.get("weak_points", []))
            if adjustment:
                report["plan_adjusted"] = True
                report["plan_adjustment"] = adjustment
        except Exception as e:  # noqa: BLE001 — 联动失败不影响模考报告
            report["plan_adjusted"] = False
            report["plan_adjustment"] = f"（联动失败：{str(e)[:80]}）"
    else:
        report = {"mode": state["mode"], "total": total, "score": score,
                  "wrong": total - sum(1 for r in results if r["correct"])}
    report["weak_points"] = state.get("weak_points", [])
    return {"report": report}


def build_practice_graph():
    """交卷后的批处理链：判分 → 诊断 → 讲题 → SM-2 → 报告。"""
    from app.graphs.common import build_linear_graph

    return build_linear_graph(PracticeState, {
        "grade_answers": _grade_answers,
        "diagnose_weak_points": _diagnose_weak_points,
        "explain_wrong": _explain_wrong,
        "schedule_reviews": _schedule_reviews,
        "build_report": _build_report,
    })


def run_submission(user_id: str, mode: str, answers: list[dict]) -> dict:
    """交卷入口：补齐题目详情 → 跑批处理链 → 返回前端所需字段。"""
    engine = get_engine()
    qids = [a["question_id"] for a in answers]
    with engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT q.id, q.type, q.stem, q.answer, q.explanation,
                   q.options::text AS opt,
                   q.source_chunk_ids::text AS sc, q.exam_point_ids::text AS ep
            FROM questions q WHERE q.id = ANY(:ids)
        """), {"ids": qids}).mappings().all()
    questions = [dict(r, options=json.loads(r["opt"] or "{}"),
                      source_chunk_ids=json.loads(r["sc"] or "[]"),
                      exam_point_ids=json.loads(r["ep"] or "[]")) for r in rows]
    g = build_practice_graph()
    state = g.invoke({"user_id": user_id, "mode": mode, "answers": answers,
                      "questions": questions, "results": [], "weak_points": [],
                      "explanations": [], "scheduled_count": 0, "report": {}})
    # 响应键保持 "scheduled"（前端契约），state 字段已更名 scheduled_count
    return {"results": state["results"], "explanations": state["explanations"],
            "weak_points": state["weak_points"], "scheduled": state["scheduled_count"],
            "report": state["report"]}
