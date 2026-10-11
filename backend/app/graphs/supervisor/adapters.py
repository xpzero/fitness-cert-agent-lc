"""子图适配器工厂：主图 ↔ 子图的状态映射按子图各写一个（name → compiled → 节点函数）。

输入键由各子图自己声明，杜绝把 QA 的私有字段静默注入其他子图；
新子图接入时在 ADAPTERS 登记（intent 名与节点名一致）。
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from app.config import settings
from app.graphs.supervisor.nodes import FALLBACK_NOTICE_MSG
from app.graphs.supervisor.state import MainState

logger = logging.getLogger(__name__)


def _last_user_message(state: MainState) -> str:
    for m in reversed(state["messages"]):
        if m.get("role") == "user":
            return str(m["content"])
    return ""


def _recent_history(state: MainState) -> list[dict]:
    """主图 messages → 最近几轮 {role, content}（多轮记忆；排除当前这条提问）。"""
    msgs = list(state.get("messages") or [])
    if msgs and msgs[-1].get("role") == "user":
        msgs = msgs[:-1]
    out = []
    for m in msgs[-8:]:
        role = m.get("role")
        if role in ("user", "assistant"):
            out.append({"role": role, "content": str(m.get("content", ""))[:500]})
    return out


def _qa_adapter(compiled):
    """messages → QAState；结果 → reply（含结构化 sources）。"""

    def run(state: MainState) -> dict:
        subgraph_state = compiled.invoke(
            {
                "query": _last_user_message(state),
                "history": _recent_history(state),
                "rewrite_rounds": 0,
                "candidates": [],
                "cited_chunk_ids": [],
                "draft_answer": "",
                "final_answer": "",
            }
        )
        # 结构化来源（前端渲染来源卡：编号 ↔ 答案内联角标）
        by_id = {cand["chunk_id"]: cand
                 for cand in subgraph_state.get("candidates", [])}
        sources = [
            {
                "id": cid,
                "label": (by_id.get(cid) or {}).get("source_label", ""),
                "excerpt": ((by_id.get(cid) or {}).get("content", ""))[:120],
            }
            for cid in dict.fromkeys(subgraph_state.get("cited_chunk_ids", []))
            if cid in by_id
        ]
        return {
            "reply": {
                "text": subgraph_state.get("final_answer", ""),
                "refused": subgraph_state.get("outcome") == "refused",
                "error": subgraph_state.get("outcome") == "service_error",
                "citations": subgraph_state.get("cited_chunk_ids", []),
                "sources": sources,
            }
        }

    run.__name__ = "run_qa"
    return run


def _planning_adapter(compiled):
    """messages → PlanningState（对话内不带 profile，走通用计划草稿）。

    子图在 hitl_confirm 处 interrupt：对话内只取草稿输出，不进入确认/改稿循环
    （确认走「规划」标签页的独立 thread + PostgresSaver）。interrupt 需要
    checkpointer 才能正常暂停返回，故 deps 组装时给该子图挂 InMemorySaver
    （草稿不跨进程持久——对话内本就不恢复它），适配器按次换 thread 防串扰。
    """

    def run(state: MainState) -> dict:
        import uuid

        subgraph_state = compiled.invoke(
            {
                "user_id": state["user_id"],
                "profile": {},
                "cert_comparison": [],
                "recommended_path": {},
                "plan": {},
                "human_feedback": "",
                "plan_status": "draft",
                "text": "",
            },
            {
                "configurable": {
                    "thread_id": f"plan-chat-{state['user_id']}-{uuid.uuid4().hex[:8]}"
                }
            },
        )
        compare = "\n".join(
            f"· {cert['name']}（{cert['issuer']}）：{cert['fee_range']}"
            for cert in subgraph_state.get("cert_comparison", [])
        )
        path = subgraph_state.get("recommended_path", {})
        plan = subgraph_state.get("plan", {})
        phases = "\n".join(
            f"· {p.get('name', '')} {p.get('weeks', '')}：{p.get('daily_tasks', '')}"
            f"（里程碑：{p.get('milestone', '')}）"
            for p in (plan.get("phases") or [])
        )
        final = (
            (f"证书对比：\n{compare}" if compare else "")
            + f"\n\n推荐：{path.get('primary', '')} —— {path.get('primary_reason', '')}"
            + f"\n备选：{path.get('backup', '')} —— {path.get('backup_reason', '')}"
            + (
                f"\n\n{plan.get('weeks', '')} 周通用计划草稿：\n{phases}"
                if phases
                else ""
            )
            + "\n\n👉 以上为通用草稿。到「规划」标签页填写背景信息"
            "（身份/城市/每周学习时长/考试日期）并确认，即可生成并保存你的专属计划。"
        )
        return {
            "reply": {
                "text": final.strip(),
                "plan": plan,
                "path": path,
                "cert_compare": subgraph_state.get("cert_comparison", []),
            }
        }

    run.__name__ = "run_planning"
    return run


def _quizgen_adapter(compiled):
    """messages → QuizGenState；accepted 结构化返回（题目卡可由前端直接渲染）。

    n_points 生成 2-3 道再由闸门筛选——"考我"单道生成会确定性卡死在同一个
    弱考点上（选题按"题最少优先"排序，重试也命中同一个）；首轮颗粒无收时
    带 exclude_points 换一批考点重试一次（batch_generate 同款模式）。
    """

    def run(state: MainState) -> dict:
        text = _last_user_message(state)
        base = {
            "cert_id": settings.default_cert,
            "n_points": 3 if "模拟卷" in text else 2,
            # 模拟卷仿真笔试：四大证均为四选一单选（README 改进待办）
            "question_type": "single" if "模拟卷" in text else "",
            "exam_points": [], "drafts": [], "accepted": [],
            "rejected": [], "coverage_delta": [], "exclude_points": [],
        }
        subgraph_state = compiled.invoke(dict(base))
        accepted = subgraph_state.get("accepted", [])
        rejected = subgraph_state.get("rejected", [])
        if not accepted and subgraph_state.get("exam_points"):
            # 换一批考点重试（排除首轮全灭的考点）
            subgraph_state = compiled.invoke({**base, "exclude_points": [
                p["id"] for p in subgraph_state["exam_points"]]})
            accepted = subgraph_state.get("accepted", [])
            rejected = rejected + subgraph_state.get("rejected", [])
        blocks = []
        for i, draft in enumerate(accepted, 1):
            opts = "　".join(f"{k}. {v}" for k, v in (draft.options or {}).items())
            blocks.append(
                f"📝 第{i}题（{draft.point_title}）\n{draft.stem}\n{opts}".rstrip()
                + f"\n答案：{draft.answer}｜质量分 {draft.quality_score}"
                + (f"｜解析：{draft.explanation[:160]}" if draft.explanation else "")
            )
        if blocks:
            final = "\n\n".join(blocks)
            if rejected:
                # 闸门拒绝率只进日志（观测面）——建设过程不进用户文案
                logger.info("quizgen 拒绝 %d 题：%s", len(rejected),
                            [r.get("reason", "")[:60] for r in rejected[:3]])
        elif subgraph_state.get("exam_points"):
            reasons = "；".join(r.get("reason", "")[:60] for r in rejected[:2])
            final = (
                "本轮出题未通过质量闸（闸门：证据定位/查重/质量分/对抗评审）"
                + (f"——{reasons}" if reasons else "")
                + "。可换个说法或指定章节（如「考我运动生理学」），"
                "或到「刷题」标签页练习已过闸题库。"
            )
        else:
            final = (
                "没有可选的考点（考点树为空或证书未配置）。"
                "请检查 syllabus 摄取与 DEFAULT_CERT 配置。"
            )
        return {
            "reply": {
                "text": final,
                "questions": [asdict(d) for d in accepted],
                "rejected": rejected,
            }
        }

    run.__name__ = "run_quizgen"
    return run


def _tutor_adapter(_compiled=None):
    """导师 agent：无静态子图——导师图按 state.user_id 现装（工具闭包绑定用户）。"""

    def run(state: MainState) -> dict:
        from app.graphs.tutor.graph import run_tutor

        out = run_tutor(state["user_id"], _last_user_message(state),
                        history=_recent_history(state))
        return {"reply": {"text": out.get("reply") or FALLBACK_NOTICE_MSG,
                                    "tutor_steps": out.get("steps_trace") or []}}

    run.__name__ = "run_tutor"
    return run


# 适配器注册表；新子图接入时在此登记（intent 名与节点名一致）。
# 签名统一 (compiled=None)：静态子图适配器闭包持有 compiled；tutor 不用。
ADAPTERS = {
    "qa": _qa_adapter,
    "planning": _planning_adapter,
    "quizgen": _quizgen_adapter,
    "tutor": _tutor_adapter,
}
REGISTERED = tuple(ADAPTERS)  # route 的合法路由目标
