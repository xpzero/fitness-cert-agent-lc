"""学情诊断 agent——原生 tool-calling 版。

结构：investigate（create_agent 工具环）→ synthesize（gen 档合成结构化报告）。
环与收尾分离（原生循环语义：模型不再请求工具即出环，无需 finish 协议）。

报告的每条 finding 必须带 {metric, value, source_tool} 数据出处——
评测端重放工具核对数值（学情版 grounding，见 run_diagnosis_eval.py）。

降级链保留：环内无任何工具调用（LLM 失败/直接回答）→ synthesize 基于
空轨迹收尾；steps 为空 → 规则版统计兜底（degraded=True，前端提示稍后重试）。
"""
from __future__ import annotations

import json
import uuid
from typing import TypedDict

from sqlalchemy import text as sql_text

from app.config import settings
from app.db import get_engine
from app.graphs.diagnosis.tools import build_diagnosis_tools
from app.graphs.native import build_native_agent, make_model, messages_to_steps
from app.llm import llm_client
from app.prompts.diagnosis import DIAGNOSIS_SYSTEM, SYNTHESIZE_PROMPT


class DiagnosisState(TypedDict, total=False):
    messages: list          # create_agent 状态（对话消息）
    user_id: str
    cert_id: str
    steps: list             # 调查轨迹（SSE/评测消费）
    report: dict | None
    degraded: bool          # True = 规则版兜底（agent 链路不可用）


def _rule_based_report(user_id: str) -> dict:
    """降级兜底：直查两项核心统计，格式对齐 agent 版报告。"""
    from app.graphs.diagnosis.tools import build_diagnosis_tools as _bdt
    tools = {t.name: t for t in _bdt(user_id)}
    acc = tools["chapter_accuracy"].invoke({})
    backlog = tools["wrongbook_backlog"].invoke({})
    return {"findings": [
                {"chapter": "全部章节", "symptom": acc,
                 "evidence": {"metric": "chapter_accuracy", "value": acc,
                              "source_tool": "chapter_accuracy"}},
                {"chapter": "错题本", "symptom": backlog,
                 "evidence": {"metric": "wrongbook_backlog", "value": backlog,
                              "source_tool": "wrongbook_backlog"}}],
            "suggestions": ["诊断服务降级中：以上为规则统计，稍后可重试 AI 深度诊断"],
            "degraded": True}


def synthesize(state: dict) -> dict:  # type: ignore[type-arg]
    """收尾：把调查轨迹合成结构化报告（findings 必带数据出处）。"""
    steps = messages_to_steps(state.get("messages") or [])
    if not steps:
        return {"steps": steps, "report": _rule_based_report(
                    state.get("user_id", "")), "degraded": True}
    transcript = "\n".join(
        f"- [{s['tool']}] {s['output']}" for s in steps)
    try:
        report = llm_client.chat_json(
            [{"role": "user",
              "content": SYNTHESIZE_PROMPT.format(transcript=transcript)}],
            model_tier="gen", max_tokens=1200)
    except Exception:  # noqa: BLE001 — 合成失败 → 规则版兜底
        return {"steps": steps, "report": _rule_based_report(
                    state.get("user_id", "")), "degraded": True}
    report.setdefault("findings", [])
    report.setdefault("suggestions", [])
    report["steps_trace"] = [
        {"tool": s["tool"], "thought": s["thought"]} for s in steps]
    return {"steps": steps, "report": report, "degraded": False}


def build_diagnosis_graph(user_id: str, cert_id: str = ""):
    """按用户装配诊断图（工具闭包绑定 user_id；编译开销可忽略）。"""
    from langgraph.graph import END, StateGraph

    agent = build_native_agent(
        model=make_model(settings.fast_model, settings.fast_base_url,
                         settings.llm_api_key),
        tools=build_diagnosis_tools(user_id, cert_id),
        system_prompt=DIAGNOSIS_SYSTEM,
        max_tool_calls=settings.diagnosis_max_steps)

    g = StateGraph(DiagnosisState)
    g.add_node("investigate", agent)
    g.add_node("synthesize", synthesize)
    g.set_entry_point("investigate")
    g.add_edge("investigate", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


def finalize_report(state: dict, user_id: str, cert_id: str = "") -> dict:
    """环结束后收尾（同步入口与 SSE 路由共用）：应用计划调整 + 落库。"""
    report = state.get("report") or {}
    report["degraded"] = bool(state.get("degraded"))

    adjustment = report.get("plan_adjustment") or {}
    weak = adjustment.get("weak_chapters") or []
    if weak and adjustment.get("action_text"):
        from app.graphs.planning.graph import apply_plan_adjustment

        applied = apply_plan_adjustment(user_id, weak,
                                        adjustment["action_text"])
        report["plan_adjusted"] = bool(applied)
    else:
        report["plan_adjusted"] = False

    with get_engine().begin() as conn:
        conn.execute(sql_text("""
            INSERT INTO diagnosis_reports (id, user_id, cert_id, findings,
                                           suggestions, steps)
            VALUES (:id, :u, :c, CAST(:f AS jsonb), CAST(:s AS jsonb),
                    CAST(:st AS jsonb))
        """), {"id": "diag-" + uuid.uuid4().hex[:10], "u": user_id,
               "c": cert_id,
               "f": json.dumps(report.get("findings", []), ensure_ascii=False),
               "s": json.dumps(report.get("suggestions", []), ensure_ascii=False),
               "st": json.dumps(report.get("steps_trace", []), ensure_ascii=False)})
    return report


def run_diagnosis(user_id: str, cert_id: str = "") -> dict:
    """同步入口：跑完工具环 → 应用计划调整 → 落库 diagnosis_reports。

    SSE 流式入口见 api/routes/quiz.py 的 /quiz/diagnose（同图 astream）。
    """
    graph = build_diagnosis_graph(user_id, cert_id)
    state = graph.invoke({"messages": [{
        "role": "user",
        "content": f"诊断用户 {user_id} 的学情并给出补弱建议"}],
        "user_id": user_id, "cert_id": cert_id,
        "steps": [], "report": None})
    return finalize_report(state, user_id, cert_id)
