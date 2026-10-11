"""主图装配：classify 统一入口，按 intent 路由到已注册子图或平凡节点。"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graphs.supervisor.adapters import ADAPTERS
from app.graphs.supervisor.nodes import fallback_notice, smalltalk
from app.graphs.supervisor.router import classify_intent, route
from app.graphs.supervisor.state import MainState


def build_main_graph(subgraphs: dict[str, object] | None = None):
    """装配主图：classify 统一入口，按 intent 路由到已注册子图或 todo/smalltalk。

    传入的 subgraphs 是 {intent 名: compiled 子图}，由 deps.get_main_graph() 组装；
    每个子图经 ADAPTERS 的适配节点包装（状态映射见各适配器 docstring）。
    """
    g = StateGraph(MainState)
    g.add_node("classify", classify_intent)
    g.add_node("smalltalk", smalltalk)
    g.add_node("fallback_notice", fallback_notice)
    for name, subgraph in (subgraphs or {}).items():
        adapter = ADAPTERS.get(name)
        if adapter is None:
            raise KeyError(f"子图 {name!r} 缺少主图适配器（supervisor.ADAPTERS）")
        g.add_node(name, adapter(subgraph))
    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        route,
        {
            "smalltalk": "smalltalk",
            "fallback_notice": "fallback_notice",
            **{n: n for n in (subgraphs or {})},
        },
    )
    for name in subgraphs or {}:
        g.add_edge(name, END)
    g.add_edge("smalltalk", END)
    g.add_edge("fallback_notice", END)
    return g.compile()
