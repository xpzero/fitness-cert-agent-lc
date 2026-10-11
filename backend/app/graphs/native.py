"""原生 tool-calling 构件：diagnosis / tutor / coach 共用。

create_agent（LangChain 1.x）承担模型-工具循环；本模块提供：
- build_native_agent：统一装配（模型档位、工具绑定、步数闸）
- messages_to_steps：把 ToolMessage 轨迹转成旧版 steps 结构
  （SSE 事件与 synthesize 的 transcript 消费此格式，前端零改动）
"""
from __future__ import annotations

from typing import Callable, Iterable

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool


def make_model(model_name: str, base_url: str, api_key: str):
    """OpenAI 兼容协议模型（智谱等），经 init_chat_model 工厂。"""
    return init_chat_model(
        f"openai:{model_name}",
        base_url=base_url, api_key=api_key, timeout=60,
        max_retries=2, temperature=0.2,
    )


def build_native_agent(*, model, tools: list[BaseTool],
                       system_prompt: str, max_tool_calls: int = 8):
    """create_agent + 步数闸（run 级限次，超限 continue 出环进收尾）。"""
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[ToolCallLimitMiddleware(run_limit=max_tool_calls)],
    )


def messages_to_steps(messages: Iterable) -> list[dict]:
    """ToolMessage 轨迹 → 旧版 steps 记录（tool/input/thought/output）。

    thought 取对应 tool_call 前最后一条模型文本（原生循环里模型未必
    每步都说话，取不到给空串——前端已容错）。
    """
    steps: list[dict] = []
    last_text = ""
    for m in messages:
        kind = getattr(m, "type", "")
        if kind == "ai" and not getattr(m, "tool_calls", None):
            last_text = str(m.content or "")[:200]
        elif kind == "tool":
            steps.append({"tool": getattr(m, "name", ""),
                          "input": None, "thought": last_text,
                          "output": str(m.content or "")[:600]})
            last_text = ""
    return steps
