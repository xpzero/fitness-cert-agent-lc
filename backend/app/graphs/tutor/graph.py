"""子图F：会话级导师 agent（W5）——把各能力当工具连续调用的真 agent。

与 supervisor 静态路由的区别：supervisor 一句话只能分诊到一个科室；
导师接诊后全程跟进——查学情（诊断环）→ 出题（quizgen）→ 调计划（planning），
下一步取决于上一步结果（动态控制流）。复用 common.build_agent_loop，
工具按 user_id 闭包绑定，图按次编译（同 diagnosis 惯例）。
"""
from __future__ import annotations

from typing import TypedDict

from sqlalchemy import text as sql_text

from app.config import settings
from app.db import get_engine
from app.graphs.common import AgentLoopState, build_agent_loop
from app.graphs.diagnosis.tools import DiagnosisTools
from app.llm import llm_client
from app.prompts.router import TUTOR_SYSTEM


class TutorState(AgentLoopState, total=False):
    user_id: str


def _arg_query(inp) -> str:
    if isinstance(inp, dict):
        return str(inp.get("query") or inp.get("topic") or
                   inp.get("text") or "").strip()
    return str(inp or "").strip()


def _qa_answer(user_id: str):
    def qa_answer(inp) -> str:
        """教材溯源问答：查教材回答知识问题，返回带出处的回答文本。"""
        from app.graphs.qa.graph import build_qa_graph

        query = _arg_query(inp)
        if not query:
            return "query 为空"
        state = build_qa_graph().invoke({
            "query": query, "refused": False, "error": False,
            "rewrite_rounds": 0, "candidates": [], "cited_chunk_ids": [],
            "draft_answer": "", "final_answer": ""})
        answer = state.get("final_answer", "")
        if state.get("refused"):
            return "（该问题无法从教材溯源，已拒答）"
        return answer[:800]
    return qa_answer


def _generate_quiz(user_id: str):
    def generate_quiz(inp) -> str:
        """定向出题：按主题/章节出 1 道题（走全套出题闸门），返回题面。"""
        from app.graphs.quizgen.graph import build_quizgen_graph

        topic = _arg_query(inp)
        seed: list[str] = []
        if topic:
            with get_engine().connect() as conn:
                rows = conn.execute(sql_text(
                    "SELECT id FROM exam_points WHERE parent_id <> '' "
                    "AND (title ILIKE :t OR chapter ILIKE :t) LIMIT 3"),
                    {"t": f"%{topic}%"}).all()
            seed = [r[0] for r in rows]
        # 至少放一题：seed 检索的考点全灭时退回覆盖分析（default_cert）换
        # 考点再试一次。原实现无 seed 时 cert_id 传空串——覆盖分析选不到
        # 任何考点，"考我"类不带主题的请求会稳定空手。
        attempts: list[tuple[list[str], list[str]]] = [(seed, [])]
        if seed:
            attempts.append(([], []))
        accepted: list = []
        for att_seed, att_exclude in attempts:
            state = build_quizgen_graph().invoke({
                "cert_id": settings.default_cert, "n_points": 1,
                "seed_points": att_seed, "exclude_points": att_exclude})
            accepted = state.get("accepted") or []
            if accepted:
                break
        if not accepted:
            return ("这个考点暂时出不了合格的题（未过质量闸），"
                    "换个说法或指定章节（如「考我运动生理学」）试试")
        d = accepted[0]
        opts = " ".join(f"{k}.{v}" for k, v in (d.options or {}).items())
        return f"题目（{d.point_title}）：{d.stem} {opts}（答案 {d.answer}）"
    return generate_quiz


def _diagnose(user_id: str):
    def diagnose(_inp) -> str:
        """学情诊断：调查答题/错题/模考/计划数据，返回结构化发现。"""
        from app.graphs.diagnosis.graph import build_diagnosis_graph

        state = build_diagnosis_graph(user_id, "").invoke(
            {"task": f"诊断用户 {user_id} 的学情", "user_id": user_id,
             "cert_id": "", "steps": [], "final_report": None})
        report = state.get("final_report") or {}
        findings = "；".join(
            f"{f.get('chapter', '?')}：{f.get('symptom', '')}"
            for f in report.get("findings", [])[:4])
        suggestions = "；".join(report.get("suggestions", [])[:3])
        return f"发现：{findings or '无数据'}。建议：{suggestions or '无'}"
    return diagnose


def _plan_state(user_id: str):
    def plan_state(_inp) -> str:
        """查当前学习计划：阶段、距考天数、历史调整。"""
        return DiagnosisTools().plan_state(user_id)
    return plan_state


def _plan_adjust(user_id: str):
    def plan_adjust(inp) -> str:
        """调整学习计划：weak_chapters（章节名列表）+ action_text（一句话行动）。"""
        from app.graphs.planning.graph import apply_plan_adjustment

        weak = (inp.get("weak_chapters") if isinstance(inp, dict) else None) or []
        action = (inp.get("action_text") if isinstance(inp, dict) else "") or ""
        if not weak or not action:
            return "需要 weak_chapters 与 action_text"
        applied = apply_plan_adjustment(user_id, [str(w) for w in weak], str(action))
        return "已写入 active 计划" if applied else "无 active 计划，未调整"
    return plan_adjust


def build_tutor_tools(user_id: str) -> dict:
    return {"qa_answer": _qa_answer(user_id),
            "generate_quiz": _generate_quiz(user_id),
            "diagnose": _diagnose(user_id),
            "plan_state": _plan_state(user_id),
            "plan_adjust": _plan_adjust(user_id)}


def _make_finish_fn():
    """收尾：把工具轨迹合成给用户的一句完整回复。"""

    def finish(state: dict) -> dict:
        steps = state.get("steps") or []
        transcript = "\n".join(f"- [{s['tool']}] {s['output'][:300]}"
                               for s in steps) or "（未调用工具）"
        try:
            out = llm_client.chat_json(
                [{"role": "system",
                  "content": "你是健身考证导师。根据工具调查结果，给用户一段"
                             "完整、可执行的回复（≤200字，口语化，可分点）。"
                             "只输出 JSON：{\"reply\": \"…\"}"},
                 {"role": "user", "content": transcript}],
                model_tier="gen", max_tokens=800)
            reply = str(out.get("reply", "")).strip()
        except Exception:  # noqa: BLE001
            reply = "（导师服务暂时不可用，请稍后再试）"
        return {"final_report": {"reply": reply or "（无回复）",
                                 "steps_trace": [{"tool": s["tool"]}
                                                  for s in steps]}}

    return finish


def build_tutor_graph(user_id: str, max_steps: int = 6):
    """按用户装配导师图（工具闭包绑定 user_id）。"""
    return build_agent_loop(TutorState, system_prompt=TUTOR_SYSTEM,
                            tools=build_tutor_tools(user_id),
                            finish_fn=_make_finish_fn(),
                            max_steps=max_steps)


def run_tutor(user_id: str, message: str, history: list[dict] | None = None) -> dict:
    """导师入口：跑完工具环，返回 {reply, steps_trace}。history=会话内上文。"""
    hist_block = ""
    if history:
        lines = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}：{str(m.get('content', ''))[:200]}"
            for m in history[-6:])
        hist_block = f"\n\n对话历史（供理解指代与上下文）：\n{lines}"
    graph = build_tutor_graph(user_id)
    state = graph.invoke({"task": f"用户请求：{message}{hist_block}", "user_id": user_id,
                          "steps": [], "final_report": None})
    return state.get("final_report") or {"reply": "（导师未能完成请求）"}
