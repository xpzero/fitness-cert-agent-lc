"""刷题端点：开始/交卷/收藏/徽章/考点覆盖 + 学情诊断+ 讲题教练。

本路由服务于 practice 子图（刷题判分链路）；AI 出题是另一张 quizgen 子图
（对话内「考我」触发，或 scripts/batch_generate.py 批量出题）——生成是
系统内部能力，不设用户直连端点。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import sse
from app.api.schemas import (
    QUIZ_MODES,
    CoachAnswerRequest,
    CoachMessageRequest,
    CoachStartRequest,
    DiagnoseRequest,
    FavoriteRequest,
    QuizStartRequest,
    QuizSubmitRequest,
)
from app.config import settings
from app.db import database
from app.services.quiz_stats import stats
from app.services.repositories import repo

router = APIRouter()


@router.post("/quiz/start")
def quiz_start(req: QuizStartRequest) -> dict:
    """选题（不含答案）。mode: practice | mock | wrong_review | favorites"""
    from app.graphs.practice.graph import start_questions

    if req.mode not in QUIZ_MODES:
        raise HTTPException(status_code=400,
                            detail=f"mode 须为 {'|'.join(QUIZ_MODES)}")
    return {"mode": req.mode, "questions": start_questions(
        req.user_id, req.mode, req.cert_id or settings.default_cert, req.count)}


@router.post("/quiz/submit")
def quiz_submit(req: QuizSubmitRequest) -> dict:
    """交卷：确定性判分 → 薄弱点 → 讲题 → SM-2 → 报告。"""
    from app.graphs.practice.graph import run_submission

    return run_submission(req.user_id, req.mode, req.answers)


@router.post("/quiz/diagnose")
async def quiz_diagnose(req: DiagnoseRequest):
    """SSE 学情诊断：step（调查步骤时间线）→ report（结构化报告）。

    原生工具环经 astream(stream_mode=["updates"], subgraphs=True) 暴露每次
    工具调用：agent 子图内 tools 节点的增量 update 累积成消息轨迹，再由
    messages_to_steps 转成 step 记录（tool/thought/output）供前端时间线。
    结束后 report 事件带完整诊断（含 plan_adjusted）。
    """
    from app.graphs.diagnosis.graph import build_diagnosis_graph

    graph = build_diagnosis_graph(req.user_id, req.cert_id)

    async def sse_stream():
        yield sse({"event": "start"})
        async for event in _diagnosis_events(graph, req.user_id, req.cert_id):
            yield sse(event)

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


async def _diagnosis_events(graph, user_id: str, cert_id: str):
    """消费原生 agent 的 updates 流，产出 step / report 事件序列。"""
    from app.graphs.diagnosis.graph import finalize_report
    from app.graphs.native import messages_to_steps

    final_state: dict = {}
    msgs: list = []          # 子图内累积的消息轨迹（model/tools 增量）
    emitted = 0              # 已发出的 step 数
    async for ns, _mode, payload in graph.astream(
        {"messages": [{"role": "user",
                       "content": f"诊断用户 {user_id} 的学情并给出补弱建议"}],
         "user_id": user_id, "cert_id": cert_id,
         "steps": [], "final_report": None},
        stream_mode=["updates"], subgraphs=True,
    ):
        if not isinstance(payload, dict):
            continue
        if not ns:
            # 顶层节点 update：收集收尾状态（steps/final_report/degraded）
            for update in payload.values():
                if isinstance(update, dict):
                    final_state.update({k: v for k, v in update.items()
                                        if k in ("steps", "final_report",
                                                 "degraded")})
            continue
        # agent 子图内：累积消息，tools 节点出结果即转 step 增量发出
        for node, update in payload.items():
            if not (isinstance(update, dict) and update.get("messages")):
                continue
            msgs.extend(update["messages"])
            if node == "tools":
                steps = messages_to_steps(msgs)
                for s in steps[emitted:]:
                    yield {"event": "step", **s}
                emitted = len(steps)
    report = finalize_report(final_state, user_id, cert_id)
    yield {"event": "report", "report": report}


# ---------------------------------------------------------------- 讲题教练

@router.post("/quiz/coach/start")
def coach_start(req: CoachStartRequest) -> dict:
    """开始教练会话：载入错题上下文，教练给出第一句（probe 反问）。"""
    from app.services.coach_service import start_session

    out = start_session(req.user_id, req.question_id)
    if "error" in out:
        raise HTTPException(status_code=404, detail=out["error"])
    return out


@router.get("/quiz/coach/active")
def coach_active(user_id: str, question_id: str) -> dict:
    """刷新恢复：该题进行中的教练会话（消息/阶段/未作答变式题）；无则空对象。"""
    from app.services.coach_service import get_active_session

    return get_active_session(user_id, question_id) or {}


@router.post("/quiz/coach/message")
def coach_message(req: CoachMessageRequest) -> dict:
    """考生发言 → 教练回应；verify 就绪时携带变式题（走全套出题闸门）。"""
    from app.services.coach_service import send_message

    out = send_message(req.session_id, req.text)
    if "error" in out:
        raise HTTPException(status_code=404, detail=out["error"])
    return out


@router.post("/quiz/coach/answer")
def coach_answer(req: CoachAnswerRequest) -> dict:
    """变式题作答：确定性判分 → 写回原题 SM-2 → 关闭会话。"""
    from app.services.coach_service import answer_variant

    out = answer_variant(req.session_id, req.answer)
    if "error" in out:
        raise HTTPException(status_code=404, detail=out["error"])
    return out


@router.post("/quiz/favorite")
def quiz_favorite(req: FavoriteRequest) -> dict:
    """收藏/取消收藏题目。"""
    from sqlalchemy import text as sql_text

    with database.engine.begin() as conn:
        if req.on:
            conn.execute(sql_text("""
                INSERT INTO favorites (user_id, question_id) VALUES (:u, :q)
                ON CONFLICT DO NOTHING
            """), {"u": req.user_id, "q": req.question_id})
        else:
            conn.execute(sql_text("DELETE FROM favorites WHERE user_id = :u AND question_id = :q"),
                         {"u": req.user_id, "q": req.question_id})
    return {"ok": True, "on": req.on,
            "total": repo.favorite_count(req.user_id)}


@router.get("/quiz/questions/{qid}/sources")
def quiz_question_sources(qid: str) -> dict:
    """题目教材依据：题干引用的表格/原文都在源 chunk 里（页面按需展开展示）。"""
    from sqlalchemy import text as sql_text

    with database.engine.connect() as conn:
        row = conn.execute(sql_text(
            "SELECT source_chunk_ids::text FROM questions WHERE id = :q"),
            {"q": qid}).first()
    if not row:
        raise HTTPException(404, "题目不存在")
    refs = repo.chunks_by_ids(json.loads(row[0]))
    return {"sources": [
        {"chunk_id": cid, "title": r.title, "page_no": r.page_no,
         "content": r.content}
        for cid, r in refs.items()]}


@router.get("/quiz/badges")
def quiz_badges(user_id: str = "web") -> dict:
    return stats.badge_counts(user_id)


@router.get("/coverage/{cert_id}")
def coverage(cert_id: str) -> dict:
    return stats.coverage_summary(cert_id)
