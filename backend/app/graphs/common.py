"""子图公共构件：纯线性链的图装配助手（practice/quizgen）。

build_linear_graph：节点按传入顺序串成 entry → n1 → … → END。
含条件边或工具环的图（qa/planning/diagnosis/tutor）不用此助手。
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph


def build_linear_graph(state_cls: type, nodes: dict[str, Callable]):
    """按 dict 顺序把节点串成线性图并编译。"""
    graph = StateGraph(state_cls)
    for name, node_fn in nodes.items():
        graph.add_node(name, node_fn)
    names = list(nodes)
    graph.set_entry_point(names[0])
    for src, dst in zip(names, names[1:]):
        graph.add_edge(src, dst)
    graph.add_edge(names[-1], END)
    return graph.compile()
