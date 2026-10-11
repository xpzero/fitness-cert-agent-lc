"""主图：意图路由 supervisor（设计文档 §4.0；W5 升级为两级路由 + 导师 agent）。

包内按职责平铺（自原单文件 supervisor.py 迁移，行为与对外 API 不变）：
- state.py    MainState + merge_messages 归约器
- router.py   两级路由：规则快路径 + chat_fast LLM 路由（classify_intent / route）
- nodes.py    smalltalk / fallback_notice 平凡节点
- adapters.py 子图适配器工厂 + ADAPTERS 注册表（状态映射见各 docstring）
- graph.py    build_main_graph 装配

子图以"适配节点"方式接入：父图状态(messages) → 子图输入(query)，
子图输出(final) → 父图 subgraph_output。已挂 qa / planning / quizgen / tutor；
practice（刷题/模考）是两段式表单交互，无法由单条消息驱动，仍走「刷题」标签页。

路由两级（W5）：
1. 规则快路径（P1 保留）：关键词命中直通子图——零成本零延迟；
2. chat_fast LLM 路由：规则未命中时判 intent + confidence（验收 ≥0.92，
   eval/scripts/run_intent_eval.py）；tutor 或低置信的开放式消息交给导师
   agent——它能把 qa/quizgen/诊断/调计划当工具连续调用（动态控制流）。
"""
from __future__ import annotations

from app.graphs.supervisor.adapters import ADAPTERS
from app.graphs.supervisor.graph import build_main_graph
from app.graphs.supervisor.nodes import FALLBACK_NOTICE_MSG
from app.graphs.supervisor.router import classify_intent, route
from app.graphs.supervisor.state import MainState

__all__ = [
    "ADAPTERS",
    "FALLBACK_NOTICE_MSG",
    "MainState",
    "build_main_graph",
    "classify_intent",
    "route",
]
