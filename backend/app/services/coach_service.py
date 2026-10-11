"""苏格拉底讲题教练（W4）：消息驱动的会话状态机。

为什么不做成 LangGraph 图：与 practice 同理（两段式表单交互不适合单次图执行）
——每条用户消息一次 LLM 调用，会话状态存 coach_sessions 表（messages/phase），
跨请求续话。状态机 probe → hint → explain → verify → done 由 LLM 输出的
next_phase 驱动，硬约束（超轮必讲透、verify 才出变式题）由代码把关。

闭环咬合点：变式题结果写回**原题**的 SM-2 排程（对话结果驱动复习排程）；
变式题本身走 quizgen 全套闸门（seed_points 定向出题 + 查重天然防与原题重复）。
"""
from __future__ import annotations

import json
import uuid
from datetime import date

from sqlalchemy import text as sql_text

from app.config import settings
from app.db import get_engine
from app.llm import llm_client
from app.prompts.practice import COACH_SYSTEM
from app.services.repositories import repo
from app.tools.grader import grade, resolve_answer_key
from app.tools.sm2 import Sm2Record, new_record, review


def _load_question(question_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(sql_text("""
            SELECT id, cert_id, type, stem, options::text AS opt, answer,
                   explanation, source_chunk_ids::text AS sc,
                   exam_point_ids::text AS ep
            FROM questions WHERE id = :q
        """), {"q": question_id}).mappings().first()
    if not row:
        return None
    return dict(row, options=json.loads(row["opt"] or "{}"),
                source_chunk_ids=json.loads(row["sc"] or "[]"),
                exam_point_ids=json.loads(row["ep"] or "[]"))


def _last_user_answer(user_id: str, question_id: str) -> str:
    with get_engine().connect() as conn:
        row = conn.execute(sql_text(
            "SELECT answer FROM user_answers WHERE user_id = :u "
            "AND question_id = :q ORDER BY id DESC LIMIT 1"),
            {"u": user_id, "q": question_id}).first()
    return str(row[0]) if row else ""


def _context_block(question: dict, user_answer: str) -> str:
    """固定注入的题目上下文：题面/考生答案/正确答案/原文摘录（讲题依据）。"""
    chunks = repo.chunks_by_ids(question["source_chunk_ids"][:2])
    blocks = [f"[{ref.title} · P{ref.page_no}] {ref.content[:400]}"
              for ref in chunks.values()] or ["（无原文，仅按解析讲解）"]
    opts = "　".join(f"{k}. {v}" for k, v in question["options"].items())
    return (f"题目：{question['stem']}\n选项：{opts}\n"
            f"考生答案：{user_answer or '（未作答）'}\n"
            f"正确答案：{resolve_answer_key(question['answer'], question['options'])}\n"
            f"解析：{question['explanation'] or '（无）'}\n"
            f"教材原文：\n" + "\n".join(blocks))


def _coach_reply(context: str, messages: list[dict],
                 force_explain: bool = False) -> dict:
    """一次教练调用：返回 {reply, next_phase, ready_for_variant}。"""
    extra = ("\n（已达最大对话轮数，本轮必须完整讲透并进入 verify。）"
             if force_explain else "")
    conversation = "\n".join(
        f"{'考生' if m['role'] == 'user' else '教练'}：{m['content']}"
        for m in messages[-8:])  # 上下文预算：最近 8 轮
    try:
        out = llm_client.chat_json(
            [{"role": "system", "content": COACH_SYSTEM + extra},
             {"role": "user",
              "content": f"{context}\n\n对话记录：\n{conversation}\n\n"
                         "输出教练的下一句话（JSON）。"}],
            model_tier="gen", temperature=0.4, max_tokens=600)
    except Exception as e:  # noqa: BLE001 — LLM 故障给兜底话术，会话不崩
        return {"reply": f"（教练服务暂时不可用：{str(e)[:60]}，稍后重发）",
                "next_phase": "probe", "ready_for_variant": False}
    return {"reply": str(out.get("reply", "")).strip() or "我们继续。",
            "next_phase": str(out.get("next_phase", "probe")),
            "ready_for_variant": bool(out.get("ready_for_variant"))}


def _generate_variant(question: dict) -> dict | None:
    """定向出 1 道同考点变式题（走 quizgen 全套闸门；全被拒则返回 None）。"""
    from app.graphs.quizgen.graph import build_quizgen_graph

    state = build_quizgen_graph().invoke({
        "cert_id": question["cert_id"], "n_points": 1,
        "seed_points": question["exam_point_ids"],
        "exclude_points": [],
    })
    accepted = state.get("accepted") or []
    if not accepted:
        return None
    d = accepted[0]
    return {"id": d.question_id, "type": d.question_type, "stem": d.stem,
            "options": d.options, "answer": d.answer,
            "explanation": d.explanation}


def _get_session(session_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(sql_text(
            "SELECT id, user_id, question_id, messages::text AS msgs, "
            "status, phase, variant_question_id FROM coach_sessions "
            "WHERE id = :s"), {"s": session_id}).mappings().first()
    if not row:
        return None
    return dict(row, messages=json.loads(row["msgs"] or "[]"))


def _update_session(session_id: str, *, messages: list[dict], phase: str,
                    status: str = "active", variant_id: str | None = None) -> None:
    # ended_at 按状态拼接而非 CASE WHEN :st='done'——同一绑定参数出现在两种
    # 类型语境会触发 psycopg 的 AmbiguousParameter
    sql = """
        UPDATE coach_sessions
        SET messages = CAST(:m AS jsonb), phase = :p, status = :st,
            variant_question_id = COALESCE(:v, variant_question_id)
    """
    if status == "done":
        sql += ", ended_at = now()"
    sql += " WHERE id = :s"
    with get_engine().begin() as conn:
        conn.execute(sql_text(sql),
                     {"m": json.dumps(messages, ensure_ascii=False), "p": phase,
                      "st": status, "v": variant_id, "s": session_id})


# ---------------------------------------------------------------- 对外入口

def get_active_session(user_id: str, question_id: str) -> dict | None:
    """该题最近一次 active 会话（前端刷新恢复用）；无进行中会话返回 None。"""
    with get_engine().connect() as conn:
        row = conn.execute(sql_text(
            "SELECT id, messages::text AS msgs, phase, variant_question_id "
            "FROM coach_sessions "
            "WHERE user_id = :u AND question_id = :q AND status = 'active' "
            "ORDER BY started_at DESC LIMIT 1"),
            {"u": user_id, "q": question_id}).first()
    if not row:
        return None
    out = {"session_id": row[0], "messages": json.loads(row[1] or "[]"),
           "phase": row[2]}
    if row[3]:  # 有未作答的变式题 → 一并恢复（题面从 questions 表取）
        question = _load_question(row[3])
        if question:
            out["variant"] = {"id": question["id"], "type": question["type"],
                              "stem": question["stem"],
                              "options": question["options"]}
    return out


def start_session(user_id: str, question_id: str) -> dict:
    """开场：载题 → 教练第一句（probe 反问）→ 建 coach_sessions 行。"""
    question = _load_question(question_id)
    if not question:
        return {"error": f"题目不存在：{question_id}"}
    user_answer = _last_user_answer(user_id, question_id)
    context = _context_block(question, user_answer)
    opening = _coach_reply(context, [{"role": "user", "content": "我刚做错了这题"}])
    session_id = "coach-" + uuid.uuid4().hex[:10]
    messages = [{"role": "coach", "content": opening["reply"]}]
    with get_engine().begin() as conn:
        conn.execute(sql_text("""
            INSERT INTO coach_sessions (id, user_id, question_id, messages,
                                        status, phase)
            VALUES (:id, :u, :q, CAST(:m AS jsonb), 'active', :p)
        """), {"id": session_id, "u": user_id, "q": question_id,
               "m": json.dumps(messages, ensure_ascii=False),
               "p": opening["next_phase"]})
    return {"session_id": session_id, "greeting": opening["reply"],
            "phase": opening["next_phase"]}


def send_message(session_id: str, text: str) -> dict:
    """考生发言 → 教练回应；verify 阶段就绪时携带变式题。"""
    session = _get_session(session_id)
    if not session or session["status"] != "active":
        return {"error": "会话不存在或已结束"}
    question = _load_question(session["question_id"])
    user_answer = _last_user_answer(session["user_id"], session["question_id"])
    context = _context_block(question, user_answer)

    messages = session["messages"] + [{"role": "user", "content": text}]
    n_rounds = sum(1 for m in messages if m["role"] == "user")
    out = _coach_reply(context, messages,
                       force_explain=n_rounds >= settings.coach_max_rounds)
    phase = out["next_phase"] if out["next_phase"] in (
        "probe", "hint", "explain", "verify", "done") else session["phase"]
    # 状态机硬约束：verify 只能在 explain 之后；超轮强制至少 explain
    if n_rounds >= settings.coach_max_rounds and phase in ("probe", "hint"):
        phase = "explain"

    variant = None
    if (out["ready_for_variant"] or phase == "verify") and not session["variant_question_id"]:
        variant = _generate_variant(question)
        if variant:
            out["reply"] += "\n\n📝 变式题（检验一下）：\n" + variant["stem"]
            opts = "　".join(f"{k}. {v}" for k, v in variant["options"].items())
            out["reply"] += f"\n{opts}"
            phase = "verify"

    messages.append({"role": "coach", "content": out["reply"]})
    _update_session(session_id, messages=messages, phase=phase,
                    variant_id=(variant or {}).get("id"))
    return {"reply": out["reply"], "phase": phase, "variant": variant}


def answer_variant(session_id: str, answer: str) -> dict:
    """变式题作答：确定性判分 → 写回原题 SM-2 → 关闭会话。"""
    session = _get_session(session_id)
    if not session or not session["variant_question_id"]:
        return {"error": "会话无变式题可作答"}
    question = _load_question(session["variant_question_id"])
    key = resolve_answer_key(question["answer"], question["options"])
    graded = grade(question["type"], answer, key)

    engine = get_engine()
    today = date.today()
    origin_qid = session["question_id"]
    sm2_updated = False
    with engine.begin() as conn:
        # 变式题结果驱动原题 SM-2（对话结果 → 复习排程）
        row = conn.execute(sql_text(
            "SELECT ease, interval_days, reps FROM wrong_book "
            "WHERE user_id = :u AND question_id = :q"),
            {"u": session["user_id"], "q": origin_qid}).first()
        if row:
            rec = review(Sm2Record.from_fields(row[0], row[1], row[2], today),
                         graded.is_correct, today)
            conn.execute(sql_text("""
                UPDATE wrong_book SET ease = :e, interval_days = :i,
                       reps = :r, due_date = :d
                WHERE user_id = :u AND question_id = :q
            """), {"e": rec.ease, "i": rec.interval_days, "r": rec.reps,
                   "d": rec.due_date, "u": session["user_id"], "q": origin_qid})
            sm2_updated = True
        # 变式题本身答错 → 也入错题本（新记录走答错分支）
        if not graded.is_correct:
            rec = review(new_record(today), False, today)
            conn.execute(sql_text("""
                INSERT INTO wrong_book (user_id, question_id, ease, interval_days,
                                        reps, due_date)
                VALUES (:u, :q, :e, :i, :r, :d)
                ON CONFLICT (user_id, question_id) DO NOTHING
            """), {"u": session["user_id"], "q": session["variant_question_id"],
                   "e": rec.ease, "i": rec.interval_days, "r": rec.reps,
                   "d": rec.due_date})
        conn.execute(sql_text(
            "INSERT INTO user_answers (user_id, question_id, answer, is_correct) "
            "VALUES (:u, :q, :a, :c)"),
            {"u": session["user_id"], "q": session["variant_question_id"],
             "a": answer, "c": graded.is_correct})

    closing = ("✅ 变式题答对——原题的复习间隔已拉长。" if graded.is_correct
               else "❌ 变式题仍错——原题明天会再排一次复习，建议回看原文。")
    messages = session["messages"] + [
        {"role": "user", "content": f"变式题我选：{answer}"},
        {"role": "coach", "content": closing}]
    _update_session(session_id, messages=messages, phase="done", status="done")
    return {"correct": graded.is_correct, "detail": graded.detail,
            "sm2_updated": sm2_updated, "closing": closing}
