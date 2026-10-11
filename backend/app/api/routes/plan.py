"""备考规划端点：HITL 启动/确认、驾驶舱聚合、打卡。"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter
from langgraph.types import Command

from app.api.deps import get_plan_graph
from app.api.schemas import CheckinRequest, PlanConfirmRequest, PlanStartRequest
from app.db import database
from app.services import plan_stats
from app.services.repositories import repo

router = APIRouter()


@router.post("/plan/start")
def plan_start(req: PlanStartRequest) -> dict:
    """生成学习计划 → interrupt 等确认。返回 thread_id 供 /plan/confirm 恢复。"""
    graph = get_plan_graph()
    thread_id = f"plan-{req.user_id}"
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.invoke({"user_id": req.user_id, "profile": req.profile,
                          "plan_status": "draft"}, config)
    return {"thread_id": thread_id, "pending_confirm": bool(state.get("__interrupt__")),
            "message": state.get("final", ""),
            "plan": state.get("plan", {}), "path": state.get("recommended_path", {}),
            "cert_compare": state.get("cert_comparison", [])}


@router.post("/plan/confirm")
def plan_confirm(req: PlanConfirmRequest) -> dict:
    """恢复中断：approve=true 落库生效；false 携反馈重新生成并再次中断。"""
    g = get_plan_graph()
    config = {"configurable": {"thread_id": req.thread_id}}
    state = g.invoke(Command(resume={"approve": req.approve, "feedback": req.feedback}),
                     config)
    return {"thread_id": req.thread_id,
            "pending_confirm": bool(state.get("__interrupt__")),
            "plan_status": state.get("plan_status", ""),
            "message": state.get("final", ""), "plan": state.get("plan", {})}


@router.get("/plan/overview")
def plan_overview(user_id: str = "streamlit") -> dict:
    """规划驾驶舱聚合：倒计时/覆盖/刷题量/连续打卡/模考趋势/本周任务/联动记录。"""
    plan_row = repo.active_plan_row(user_id)
    if not plan_row:
        return {"active": False}
    return plan_stats.overview_response(
        plan=json.loads(plan_row["plan_text"]), plan_id=plan_row["id"],
        exam_date=plan_row["exam_date"], today=date.today(),
        coverage_totals=repo.coverage_totals(plan_row["cert_id"]),
        answered_count=repo.answered_count(user_id),
        mock_trend=repo.recent_mock_scores(user_id),
        answer_days=repo.answer_days(user_id),
        checkins=repo.checkins_on_day(user_id, date.today()))


@router.post("/plan/checkin")
def plan_checkin(req: CheckinRequest) -> dict:
    from sqlalchemy import text as sql_text

    with database.engine.begin() as conn:
        conn.execute(sql_text("""
            INSERT INTO study_checkins (user_id, day, task_no, done)
            VALUES (:u, :d, :n, :done)
            ON CONFLICT (user_id, day, task_no) DO UPDATE SET done = :done
        """), {"u": req.user_id, "d": date.today(), "n": req.task_no, "done": req.done})
    return {"ok": True}
