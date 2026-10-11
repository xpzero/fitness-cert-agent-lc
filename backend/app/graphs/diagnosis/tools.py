"""学情诊断 agent 的工具集（W3）：全部确定性 SQL，engine 注入。

工具面向 agent 的 action_input（LLM 给的参数宽松：str 或 dict 都收），
user_id/cert_id 由 build_diagnosis_tools 闭包绑定——agent 不可指定他人，
也无需在每步重复传。每个工具返回紧凑文本（进 transcript，400 字内）。

每条输出自带"数据出处"语义（哪张表/什么口径），供 synthesize 强制
findings 引用 {metric, value, source_tool}（学情版 grounding）。
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from app.db import get_engine


def _arg(action_input, key: str = "chapter") -> str:
    """LLM 的 action_input 容错解析：{"chapter": "…"} / "…" 都收。"""
    if isinstance(action_input, dict):
        return str(action_input.get(key) or action_input.get("value") or "").strip()
    return str(action_input or "").strip()


class DiagnosisTools:
    """闭包式工具注册表：绑定 user_id/cert_id 后给 agent loop 使用。"""

    def __init__(self, engine: Engine | None = None):
        self._engine = engine

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    # ---------------------------------------------------------- 各工具
    def chapter_accuracy(self, user_id: str, _input=None) -> str:
        """各章节的答题数与正确率（按考点归属归组，来源 user_answers×questions×exam_points）。"""
        with self.engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT ep.chapter, count(*) AS total,
                       count(*) FILTER (WHERE ua.is_correct) AS correct
                FROM user_answers ua
                JOIN questions q ON q.id = ua.question_id
                JOIN exam_points ep ON ep.id = ANY(
                    ARRAY(SELECT jsonb_array_elements_text(q.exam_point_ids)))
                WHERE ua.user_id = :u
                GROUP BY ep.chapter ORDER BY total DESC
            """), {"u": user_id}).mappings().all()
        if not rows:
            return "该用户尚无答题记录"
        return "\n".join(
            f"{r['chapter']}：{r['correct']}/{r['total']}"
            f"（正确率 {r['correct'] / r['total']:.0%}）" for r in rows)

    def chapter_wrong_detail(self, user_id: str, chapter: str) -> str:
        """下钻某章的错题细节：题型分布与反复答错的题（来源 user_answers×questions）。"""
        with self.engine.connect() as conn:
            type_rows = conn.execute(sql_text("""
                SELECT q.type, count(*) AS n FROM user_answers ua
                JOIN questions q ON q.id = ua.question_id
                JOIN exam_points ep ON ep.id = ANY(
                    ARRAY(SELECT jsonb_array_elements_text(q.exam_point_ids)))
                WHERE ua.user_id = :u AND NOT ua.is_correct AND ep.chapter = :ch
                GROUP BY q.type ORDER BY n DESC
            """), {"u": user_id, "ch": chapter}).all()
            wrong_rows = conn.execute(sql_text("""
                SELECT q.stem, count(*) FILTER (WHERE NOT ua.is_correct) AS wrong_n
                FROM user_answers ua
                JOIN questions q ON q.id = ua.question_id
                JOIN exam_points ep ON ep.id = ANY(
                    ARRAY(SELECT jsonb_array_elements_text(q.exam_point_ids)))
                WHERE ua.user_id = :u AND ep.chapter = :ch
                GROUP BY q.stem HAVING count(*) FILTER (WHERE NOT ua.is_correct) >= 2
                ORDER BY wrong_n DESC LIMIT 3
            """), {"u": user_id, "ch": chapter}).all()
        if not type_rows:
            return f"章节「{chapter}」没有错题记录"
        dist = "、".join(f"{r[0]} {r[1]} 题" for r in type_rows)
        repeats = "；".join(f"「{r[0][:30]}」错 {r[1]} 次" for r in wrong_rows) or "无反复错题"
        return f"「{chapter}」错题题型分布：{dist}。反复错（≥2次）：{repeats}"

    def wrongbook_backlog(self, user_id: str, _input=None) -> str:
        """SM-2 错题本状态：到期积压量与总量（来源 wrong_book）。"""
        with self.engine.connect() as conn:
            due, total = conn.execute(sql_text(
                "SELECT count(*) FILTER (WHERE due_date <= :t), count(*) "
                "FROM wrong_book WHERE user_id = :u"),
                {"u": user_id, "t": date.today()}).one()
        if not total:
            return "错题本为空"
        return (f"错题本共 {total} 题，今日到期应复习 {due} 题"
                f"（积压率 {due / total:.0%}）")

    def mock_trend(self, user_id: str, _input=None) -> str:
        """模考分数轨迹（最近 5 次，来源 mock_reports）。"""
        with self.engine.connect() as conn:
            scores = [r[0] for r in conn.execute(sql_text(
                "SELECT score FROM mock_reports WHERE user_id = :u "
                "ORDER BY created_at DESC LIMIT 5"), {"u": user_id}).all()]
        if not scores:
            return "尚无模考记录"
        seq = list(reversed(scores))
        trend = "上升" if len(seq) > 1 and seq[-1] > seq[0] else (
            "下降" if len(seq) > 1 and seq[-1] < seq[0] else "持平")
        return f"模考分数（旧→新）：{[round(s) for s in seq]}，趋势{trend}，及格线 60"

    def plan_state(self, user_id: str, _input=None) -> str:
        """当前学习计划状态：阶段、距考天数、打卡连续性（来源 study_plans×study_checkins）。"""
        with self.engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT plan::text, exam_date FROM study_plans "
                "WHERE user_id = :u AND status = 'active' "
                "ORDER BY exam_date DESC LIMIT 1"), {"u": user_id}).first()
        if not row:
            return "无生效中的学习计划"
        plan = json.loads(row[0])
        phases = " → ".join(p.get("name", "?") for p in (plan.get("phases") or []))
        days_left = ((row[1] - date.today()).days if row[1] else None)
        adj = plan.get("adjustments") or []
        return (f"计划阶段：{phases or '（未排阶段）'}；距考试 "
                f"{days_left if days_left is not None else '?'} 天；"
                f"已累计计划调整 {len(adj)} 次")


def build_diagnosis_tools(user_id: str, cert_id: str) -> dict:
    """绑定 user_id/cert_id 的工具注册表（cert_id 备用：章节归属按题目本证的考点）。"""
    t = DiagnosisTools()
    return {
        "chapter_accuracy": lambda _inp: t.chapter_accuracy(user_id),
        "chapter_wrong_detail": lambda inp: t.chapter_wrong_detail(
            user_id, _arg(inp)),
        "wrongbook_backlog": lambda _inp: t.wrongbook_backlog(user_id),
        "mock_trend": lambda _inp: t.mock_trend(user_id),
        "plan_state": lambda _inp: t.plan_state(user_id),
    }
