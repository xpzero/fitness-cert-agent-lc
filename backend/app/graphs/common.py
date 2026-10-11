"""子图公共构件。

build_linear_graph：纯线性链（practice/quizgen）的图装配助手——
节点按传入顺序串成 entry → n1 → … → END。含条件边的图（qa/planning）不用此助手。

build_agent_loop：ReAct 式工具环——
chat_json 结构化决策（{thought, action, action_input}），不依赖原生
function-calling；LLM 失败/未知工具/步数耗尽统一走 finish_fn 收尾（不喂回错误
重试，防死循环）。步骤经 get_stream_writer 发 {"step": …} 自定义事件
（astream 消费；invoke 场景静默降级）。
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.llm import llm_client


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


class AgentLoopState(TypedDict, total=False):
    """工具环状态约定：task 是给 agent 的任务指令，steps 累积执行轨迹，
    final_report 由 finish_fn 写入（非 None 即终止）。"""
    task: str
    steps: list          # [{tool, input, thought, output}]
    final_report: dict | None


def _render_transcript(state: dict, tools_desc: str) -> str:
    steps = state.get("steps") or []
    trail = "\n".join(
        f"- [{s['tool']}] 输入: {s['input']}\n  输出: {s['output'][:400]}"
        for s in steps) or "（尚未调用任何工具）"
    return (f"任务：{state.get('task', '')}\n\n可用工具：\n{tools_desc}\n\n"
            f"已执行步骤：\n{trail}\n\n"
            "决定下一步：继续调工具收集证据，或信息足够后结束。只输出 JSON："
            '{"thought": "一句话理由", "action": "工具名或 finish", '
            '"action_input": {...工具参数...}}')


def build_agent_loop(state_cls: type, *, system_prompt: str,
                     tools: dict[str, Callable[[object], object]],
                     finish_fn: Callable[[dict], dict],
                     max_steps: int = 8):
    """装配单节点自循环的 agent 图：step 节点决策+执行，finish 条件出环。

    tools 的 key 即 action 名；工具签名 (action_input) -> 可 str() 的结果。
    finish_fn 收到含 steps 的 state，返回写 final_report 的 update dict。
    每步尝试经 stream writer 发 {"step": …}（供 SSE 时间线）。
    """
    tools_desc = "\n".join(f"- {name}: {fn.__doc__ or ''}" for name, fn in tools.items())

    def step(state: dict) -> dict:
        from langgraph.config import get_stream_writer

        steps = list(state.get("steps") or [])
        if len(steps) >= max_steps:
            return finish_fn(state)
        try:
            decision = llm_client.chat_json(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": _render_transcript(state, tools_desc)}],
                model_tier="fast", temperature=0.2)
        except Exception:  # noqa: BLE001 — 决策失败直接收尾（降级而非重试）
            return finish_fn(state)
        action = str(decision.get("action") or "")
        if action == "finish" or action not in tools:
            return finish_fn(state)
        try:
            output = tools[action](decision.get("action_input"))
        except Exception as e:  # noqa: BLE001 — 工具失败记入轨迹（agent 可换路）
            output = f"工具执行失败: {str(e)[:160]}"
        record = {"tool": action, "input": decision.get("action_input"),
                  "thought": str(decision.get("thought", ""))[:200],
                  "output": str(output)[:600]}
        try:
            get_stream_writer()({"step": record})
        except Exception:  # noqa: BLE001 — 非 astream 上下文无 writer
            pass
        return {"steps": steps + [record]}

    def has_report(state: dict) -> str:
        return "end" if state.get("final_report") is not None else "step"

    g = StateGraph(state_cls)
    g.add_node("step", step)
    g.set_entry_point("step")
    g.add_conditional_edges("step", has_report,
                            {"step": "step", "end": END})
    return g.compile()
