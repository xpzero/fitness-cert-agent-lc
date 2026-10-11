"""API 层共享依赖：图单例、SSE 帧格式、Langfuse 追踪。"""
from __future__ import annotations

import json
from functools import lru_cache

from app.graphs.qa.graph import build_qa_graph
from app.graphs.supervisor import build_main_graph


@lru_cache
def get_main_graph():
    """supervisor 主图单例：qa / planning / quizgen / tutor 四路。

    planning 在对话内只出通用草稿（InMemorySaver，按次换 thread，不恢复）；
    确认/改稿走「规划」标签页的 get_plan_graph()（PostgresSaver 持久 thread）。
    practice 是两段式表单交互，不经主图（见 supervisor.FALLBACK_NOTICE_MSG）。
    tutor 传占位 None：导师图按 state.user_id 现装（见 supervisor._tutor_adapter）。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graphs.planning.graph import build_planning_graph
    from app.graphs.quizgen.graph import build_quizgen_graph

    return build_main_graph({
        "qa": build_qa_graph(),
        "planning": build_planning_graph(checkpointer=InMemorySaver()),
        "quizgen": build_quizgen_graph(),
        "tutor": None,
    })


@lru_cache
def get_plan_graph():
    """规划子图：PostgresSaver 持久化 checkpoint——HITL 中断草稿跨进程/跨重启可恢复。"""
    from app.checkpointer import get_checkpointer
    from app.graphs.planning.graph import build_planning_graph

    return build_planning_graph(checkpointer=get_checkpointer())


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def trace_chat(user_id: str, message: str, thread_id: str, output: str) -> None:
    try:
        from langfuse import Langfuse

        lf = Langfuse()
        lf.trace(id=thread_id, session_id=user_id, name="chat",
                 input=message, output=output)
        lf.flush()
    except Exception:  # noqa: BLE001 — 观测失败不影响主链路
        pass
