"""子图F：会话级导师 agent——原生 tool-calling 版。

与 supervisor 静态路由的区别：supervisor 一句话只能分诊到一个科室；
导师接诊后全程跟进——查学情（诊断环）→ 出题（quizgen）→ 调计划（planning），
下一步取决于上一步结果（动态控制流）。

结构对齐 diagnosis：investigate（create_agent 工具环）→ synthesize
（gen 档把工具轨迹合成给用户的一段回复）。环与收尾分离（原生循环语义：
模型不再请求工具即出环，无需 finish 协议）。工具按 user_id 闭包绑定，
图按次编译（同 diagnosis 惯例）。
"""
from __future__ import annotations

from typing import TypedDict

from app.config import settings
from app.graphs.native import build_native_agent, make_model, messages_to_steps
from app.graphs.tutor.tools import build_tutor_tools
from app.llm import llm_client
from app.prompts.router import TUTOR_SYSTEM


class TutorState(TypedDict, total=False):
    messages: list          # create_agent 状态（对话消息）
    user_id: str
    steps: list             # 调查轨迹（steps_trace 消费）
    final_report: dict | None


def synthesize(state: dict) -> dict:  # type: ignore[type-arg]
    """收尾：把工具轨迹合成给用户的一句完整回复（{reply, steps_trace}）。"""
    steps = messages_to_steps(state.get("messages") or [])
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
    return {"steps": steps, "final_report": {
        "reply": reply or "（无回复）",
        "steps_trace": [{"tool": s["tool"]} for s in steps]}}


def build_tutor_graph(user_id: str, max_steps: int = 6):
    """按用户装配导师图（工具闭包绑定 user_id；编译开销可忽略）。"""
    from langgraph.graph import END, StateGraph

    agent = build_native_agent(
        model=make_model(settings.fast_model, settings.fast_base_url,
                         settings.llm_api_key),
        tools=build_tutor_tools(user_id),
        system_prompt=TUTOR_SYSTEM,
        max_tool_calls=max_steps)

    g = StateGraph(TutorState)
    g.add_node("investigate", agent)
    g.add_node("synthesize", synthesize)
    g.set_entry_point("investigate")
    g.add_edge("investigate", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


def run_tutor(user_id: str, message: str, history: list[dict] | None = None) -> dict:
    """导师入口：跑完工具环，返回 {reply, steps_trace}。history=会话内上文。"""
    hist_block = ""
    if history:
        lines = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}：{str(m.get('content', ''))[:200]}"
            for m in history[-6:])
        hist_block = f"\n\n对话历史（供理解指代与上下文）：\n{lines}"
    graph = build_tutor_graph(user_id)
    state = graph.invoke({"messages": [{
        "role": "user",
        "content": f"用户请求：{message}{hist_block}"}],
        "user_id": user_id, "steps": [], "final_report": None})
    return state.get("final_report") or {"reply": "（导师未能完成请求）"}
