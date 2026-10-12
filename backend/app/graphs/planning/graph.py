"""子图A：备考规划（背景采集→对比→路径→计划→HITL 确认）。

HITL 用 LangGraph 原生 interrupt/Command(resume)：generate_plan 后中断等用户确认，
确认通过落库 active，或按反馈经 adjust_plan 重新生成并再次中断（循环直至满意）。
interrupt 需要 checkpointer 才能暂停/恢复：「规划」标签页用 PostgresSaver
（草稿跨进程/跨重启可恢复，见 app/checkpointer.py）；对话内草稿走 InMemorySaver
（按次换 thread、不恢复——对话内本就只出草稿，确认动作在标签页完成）。
"""
from __future__ import annotations

import json
from datetime import date
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy import text as sql_text

from app.llm import llm_client
from app.db import get_engine
from app.prompts.planning import PLAN_SYSTEM

REQUIRED_PROFILE = ["identity", "city", "weekly_hours", "exam_date"]


class PlanningState(TypedDict):
    user_id: str
    profile: dict
    cert_comparison: list[dict]
    recommended_path: dict
    plan: dict
    human_feedback: str
    plan_status: str            # draft | active
    final: str


SEED_CERTS = [
    dict(id="nsca_cpt", name="NSCA-CPT 私人教练认证", issuer="美国国家体能协会（NCCA 认证）",
         fee_range="中国区考试费约 2180 元；中文考试；Pearson VUE 机考（140 计分题/3 小时）",
         urls={"中国官网报名": "https://www.nsca-shanghai.com.cn",
               "考位预约": "https://www.pearsonvue.com/nsca"}),
    dict(id="ace_cpt", name="ACE-CPT", issuer="美国运动委员会（NCCA 认证）",
         fee_range="约 359+399 美元",
         urls={"官网": "https://www.acefitness.org"}),
    dict(id="acsm_cpt", name="ACSM-CPT", issuer="美国运动医学会（与中国体育科学学会合作中文认证）",
         fee_range="培训+考试约 9800 元（含中文教材与考前培训）",
         urls={"官网": "https://www.acsm.org"}),
    dict(id="nasm_cpt", name="NASM-CPT", issuer="美国国家运动医学学会",
         fee_range="约 7800-8600 元（含线下培训可选中文考试）",
         urls={"官网": "https://www.nasm.org"}),
]


def _seed_certs(engine) -> None:
    cert_count = engine.connect().execute(
        sql_text("SELECT count(*) FROM certificates")).scalar()
    if cert_count:
        return
    with engine.begin() as conn:
        for cert in SEED_CERTS:
            conn.execute(sql_text("""
                INSERT INTO certificates (id, name, issuer, fee_range, official_urls)
                VALUES (:id, :name, :issuer, :fee_range, CAST(:urls AS jsonb))
                ON CONFLICT (id) DO NOTHING
            """), {"id": cert["id"], "name": cert["name"], "issuer": cert["issuer"],
                   "fee_range": cert["fee_range"],
                   "urls": json.dumps(cert["urls"], ensure_ascii=False)})


# ---------------------------------------------------------------- nodes

def collect_profile(state: PlanningState) -> dict:
    """背景表单校验：必填项缺失给出提示；齐全则折算"距考试周数"供后续排期。"""
    profile = state.get("profile", {})
    missing = [k for k in REQUIRED_PROFILE if not profile.get(k)]
    if missing:
        return {"plan_status": "draft",
                "message": f"缺少信息：{missing}（identity/city/weekly_hours/exam_date）"}
    weeks = max(1, round((date.fromisoformat(str(profile["exam_date"])) - date.today()).days / 7))
    return {"profile": {**profile, "weeks": weeks},
            "message": f"距离考试约 {weeks} 周", "plan_status": "draft"}


def compare_certs(state: PlanningState) -> dict:
    engine = get_engine()
    _seed_certs(engine)
    with engine.connect() as conn:
        rows = conn.execute(sql_text(
            "SELECT name, issuer, fee_range FROM certificates ORDER BY id")).mappings().all()
    return {"cert_comparison": [dict(r) for r in rows]}


def recommend_path(state: PlanningState) -> dict:
    """路径推荐（规则版，不调 LLM）：预算 <2000 元给省钱组合，否则默认 NSCA 主攻。"""
    identity = state["profile"].get("identity", "")
    budget = state["profile"].get("budget", "")
    budget_low = isinstance(budget, (int, float)) and budget < 2000
    if budget_low:
        primary, primary_reason = "nsca_cpt", "四大中费用最低（约2180元）且中国官网可直报、有中文考试"
        backup, backup_reason = "ace_cpt", "自学友好、国际认可度高（NCCA）"
    else:
        primary, primary_reason = "nsca_cpt", "国际认可度高、中国官网直报、中文考试、性价比最优"
        backup, backup_reason = "acsm_cpt", "学术权威背书强，适合走医疗康复衔接方向"
    return {"recommended_path": {"primary": primary, "primary_reason": primary_reason,
                                 "backup": backup, "backup_reason": backup_reason}}


def generate_plan(state: PlanningState) -> dict:
    """LLM 生成周计划；失败时降级为确定性骨架计划（保证链路不中断）。

    章节清单取四大证通用理论考点（id LIKE 'T%'）的去重章节——
    计划按章排期而非按证书，四大证备考内容高度重合。
    """
    cert_id = state["profile"].get("cert_id") or "nsca_cpt"
    with get_engine().connect() as conn:
        chapters = [r[0] for r in conn.execute(sql_text(
            "SELECT DISTINCT chapter FROM exam_points WHERE cert_id = :c "
            "AND id LIKE 'T%' ORDER BY chapter"),
            {"c": cert_id}).all()]
    weeks = state["profile"].get("weeks", 8)
    identity = state["profile"].get("identity", "在职")
    hours = state["profile"].get("weekly_hours", 10)
    try:
        plan = llm_client.chat_json([
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user",
             "content": f"考生备考证书：{cert_id}。考生：{identity}，每周 {hours} 小时，共 {weeks} 周。"
                        f"章节：{'、'.join(chapters)}。"
                        f"已有反馈：{state.get('human_feedback') or '无'}"},
        ], model_tier="gen", max_tokens=1200)
        plan["weeks"] = weeks
    except Exception as e:  # noqa: BLE001 — LLM 失败时给确定性骨架计划
        phase_span_weeks = max(1, weeks // 4)
        plan = {"weeks": weeks, "phases": [
            {"name": "① 基础扫盲", "weeks": f"第1-{phase_span_weeks}周",
             "chapters": chapters[:3],
             "daily_tasks": "每天 1 章 + 10 题", "milestone": "基础章节全覆盖"},
            {"name": "② 强化与专项刷题",
             "weeks": f"第{phase_span_weeks + 1}-{phase_span_weeks * 2 + 1}周",
             "chapters": chapters[3:6],
             "daily_tasks": "每天 20 题 + 错题复习", "milestone": "刷题正确率 ≥70%"},
            {"name": "③ 模考冲刺",
             "weeks": f"第{phase_span_weeks * 2 + 2}-"
                      f"{max(phase_span_weeks * 2 + 2, weeks - 1)}周",
             "chapters": chapters[6:],
             "daily_tasks": "全真模考 ×2 + 讲题复盘", "milestone": "模考 ≥70 分"},
            {"name": "④ 考前回炉", "weeks": f"第{weeks}周",
             "chapters": ["错题本", "薄弱考点"],
             "daily_tasks": "错题回炉", "milestone": "错题清零"}],
            "note": f"（LLM 规划不可用，使用骨架计划：{str(e)[:60]}）"}
    plan["primary"] = state["recommended_path"]["primary"]
    plan["weekly_hours"] = hours
    return {"plan": plan}


def hitl_confirm(state: PlanningState) -> dict:
    """interrupt：计划交给用户，等待 /plan/confirm 的 Command(resume=...)。

    interrupt 的载荷即前端确认页展示的草稿（计划+路径+证书对比）；
    resume 值约定为 {approve: bool, feedback: str}。
    """
    decision = interrupt({"plan": state["plan"],
                          "recommended_path": state["recommended_path"],
                          "cert_comparison": state["cert_comparison"]})
    if decision.get("approve"):
        return {"plan_status": "active", "human_feedback": "",
                "message": "计划已确认生效（可在刷题页按计划练习）"}
    return {"plan_status": "draft",
            "human_feedback": decision.get("feedback", "请调整"),
            "message": "已收到修改意见，重新生成计划…"}


def apply_plan_adjustment(user_id: str, weak_chapters: list[str],
                          action_text: str) -> dict | None:
    """把调整追加进 active 计划（模考联动与学情诊断 agent 共用的内核）。

    按薄弱章节在最近阶段插入补练任务，并把调整记进 plan.adjustments 历史。
    返回调整说明；无 active 计划时返回 None。
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(sql_text(
            "SELECT plan::text FROM study_plans "
            "WHERE user_id = :u AND status = 'active' ORDER BY exam_date DESC LIMIT 1"),
            {"u": user_id}).first()
    if not row:
        return None
    plan = json.loads(row[0])
    adjustment = {"date": date.today().isoformat(),
                  "weak_chapters": weak_chapters, "action": action_text}
    if weak_chapters:
        phases = plan.get("phases") or []
        if phases:
            phases[-1].setdefault("daily_tasks", "")
            phases[-1]["daily_tasks"] = (
                str(phases[-1]["daily_tasks"])
                + f"；【加练】{weak_chapters[0]}：每日 20 题 + 讲题复盘").strip("；")
    plan.setdefault("adjustments", []).append(adjustment)
    with engine.begin() as conn:
        conn.execute(sql_text(
            "UPDATE study_plans SET plan = CAST(:p AS jsonb) "
            "WHERE user_id = :u AND status = 'active'"),
            {"u": user_id, "p": json.dumps(plan, ensure_ascii=False)})
    return adjustment


def auto_adjust_from_mock(user_id: str, score: float,
                          weak_points: list[dict]) -> dict | None:
    """跨子图联动（practice → planning）：模考后自动调整 active 计划。

    规则化调整（不调 LLM，秒级返回）：按薄弱章节生成行动文案并经
    apply_plan_adjustment 写回；学情诊断 agent是其升级路径，
    本函数保留为 agent 失败时的降级路径。返回调整说明；无 active 计划返回 None。
    """
    weak_chapters = [w["chapter"] for w in weak_points] or []
    action_text = (f"模考 {score} 分，未达 60 及格线——" if score < 60
                   else "模考通过，保持节奏——")
    action_text += (f"未来 3 天重点补练：{'、'.join(weak_chapters)}"
                    if weak_chapters else "无薄弱项")
    adjustment = apply_plan_adjustment(user_id, weak_chapters, action_text)
    if adjustment:
        adjustment["mock_score"] = score
    return adjustment


def save_plan(state: PlanningState) -> dict:
    """落库为唯一 active 计划：先删该用户旧 active 再插入（单一生效原则）。"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(sql_text("DELETE FROM study_plans WHERE user_id = :u AND status = 'active'"),
                     {"u": state["user_id"]})
        conn.execute(sql_text("""
            INSERT INTO study_plans (id, user_id, cert_id, exam_date, plan, status)
            VALUES (:id, :u, :c, :e, CAST(:p AS jsonb), 'active')
        """), {"id": "plan-" + state["user_id"][:8] + date.today().isoformat(),
               "u": state["user_id"], "c": state["profile"].get("cert_id") or "nsca_cpt",
               "e": str(state["profile"].get("exam_date")),
               "p": json.dumps(state["plan"], ensure_ascii=False)})
    return {"message": "计划已保存（active）"}


def adjust_plan(state: PlanningState) -> dict:
    """按反馈重新生成：直接复用 generate_plan（它读取 human_feedback）。"""
    return generate_plan(state)


# ---------------------------------------------------------------- edges/graph

def _route_after_hitl(state: PlanningState) -> str:
    return "save_plan" if state["plan_status"] == "active" else "adjust_plan"


def build_planning_graph(checkpointer=None):
    """装配规划图。hitl_confirm 是中断点：approve → save_plan 落库；
    否则 adjust_plan 重新生成并回到 hitl_confirm——"改稿↔确认"循环，
    每一轮的中断状态都由 checkpointer 按 thread_id 持久化。"""
    g = StateGraph(PlanningState)
    g.add_node("collect_profile", collect_profile)
    g.add_node("compare_certs", compare_certs)
    g.add_node("recommend_path", recommend_path)
    g.add_node("generate_plan", generate_plan)
    g.add_node("hitl_confirm", hitl_confirm)
    g.add_node("save_plan", save_plan)
    g.add_node("adjust_plan", adjust_plan)
    g.set_entry_point("collect_profile")
    g.add_edge("collect_profile", "compare_certs")
    g.add_edge("compare_certs", "recommend_path")
    g.add_edge("recommend_path", "generate_plan")
    g.add_edge("generate_plan", "hitl_confirm")
    g.add_conditional_edges("hitl_confirm", _route_after_hitl,
                            {"save_plan": "save_plan", "adjust_plan": "adjust_plan"})
    g.add_edge("save_plan", END)
    g.add_edge("adjust_plan", "hitl_confirm")
    return g.compile(checkpointer=checkpointer)
