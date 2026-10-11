"""导师 agent 的工具集：各能力子图的薄封装，user_id 闭包绑定。

原生 @tool 定义：参数 schema 由类型注解自动生成（替代手写容错解析）。
user_id 由 build_tutor_tools 闭包绑定——agent 不可指定他人，也无需在每步
重复传。每个工具返回紧凑文本（进 transcript，800 字内）。
"""
from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import text as sql_text

from app.config import settings
from app.db import get_engine


def build_tutor_tools(user_id: str) -> list:
    """绑定 user_id 的导师工具列表（plan_state 复用诊断工具集的同名工具）。"""

    from app.graphs.diagnosis.tools import build_diagnosis_tools

    plan_state = next(t for t in build_diagnosis_tools(user_id)
                      if t.name == "plan_state")

    @tool
    def qa_answer(query: str) -> str:
        """教材溯源问答：查教材回答知识问题，返回带出处的回答文本。"""
        from app.graphs.qa.graph import build_qa_graph

        query = query.strip()
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

    @tool
    def generate_quiz(topic: str = "") -> str:
        """定向出题：按主题/章节出 1 道题（走全套出题闸门），返回题面。topic 留空则按覆盖分析自选考点。"""
        from app.graphs.quizgen.graph import build_quizgen_graph

        topic = (topic or "").strip()
        seed: list[str] = []
        if topic:
            with get_engine().connect() as conn:
                rows = conn.execute(sql_text(
                    "SELECT id FROM exam_points WHERE parent_id <> '' "
                    "AND (title ILIKE :t OR chapter ILIKE :t) LIMIT 3"),
                    {"t": f"%{topic}%"}).all()
            seed = [r[0] for r in rows]
        # seed 检索的考点全灭时退回覆盖分析（default_cert）换考点再试一次——
        # 无 seed 直接传空会让覆盖分析选不到任何考点，"考我"类不带主题的
        # 请求会稳定空手。
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

    @tool
    def diagnose() -> str:
        """学情诊断：调查答题/错题/模考/计划数据，返回结构化发现与建议。"""
        from app.graphs.diagnosis.graph import build_diagnosis_graph

        state = build_diagnosis_graph(user_id).invoke({
            "messages": [{"role": "user",
                          "content": f"诊断用户 {user_id} 的学情"}],
            "user_id": user_id, "cert_id": "",
            "steps": [], "final_report": None})
        report = state.get("final_report") or {}
        findings = "；".join(
            f"{f.get('chapter', '?')}：{f.get('symptom', '')}"
            for f in report.get("findings", [])[:4])
        suggestions = "；".join(report.get("suggestions", [])[:3])
        return f"发现：{findings or '无数据'}。建议：{suggestions or '无'}"

    @tool
    def plan_adjust(weak_chapters: list[str], action_text: str) -> str:
        """调整学习计划：weak_chapters 为薄弱章节名列表，action_text 为一句话调整行动。"""
        from app.graphs.planning.graph import apply_plan_adjustment

        weak = [str(w) for w in (weak_chapters or [])]
        action = (action_text or "").strip()
        if not weak or not action:
            return "需要 weak_chapters 与 action_text"
        applied = apply_plan_adjustment(user_id, weak, action)
        return "已写入 active 计划" if applied else "无 active 计划，未调整"

    return [qa_answer, generate_quiz, diagnose, plan_state, plan_adjust]
