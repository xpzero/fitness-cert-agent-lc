"""两级路由：规则快路径直通；未命中走轻模型结构化路由。

低置信的开放式消息交给导师（tutor 是柔性处理者，smalltalk 除外）。
LLM 路由用 with_structured_output（RouterDecision schema），替代手写 JSON 协议。
"""

from __future__ import annotations

from typing import Literal, cast

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.graphs.native import make_model
from app.graphs.supervisor.adapters import REGISTERED
from app.graphs.supervisor.state import MainState
from app.prompts.router import ROUTER_PROMPT

LLM_ROUTABLE = ("qa", "quizgen", "planning", "practice", "tutor", "smalltalk")

# 复合请求嫌疑信号：命中任一则绕过关键词快路径交给 LLM 整句判断——
# 否则"看看我的薄弱点然后出题练"会被"出题"关键词劫持到 quizgen
COMPOSITE_SIGNALS = (
    "我的",
    "看看我",
    "然后",
    "怎么办",
    "怎么复习",
    "薄弱",
    "错题本",
    "分析一下",
    "评估一下",
)

# 规则快路径：intent -> 触发关键词（dict 保序，命中顺序即优先级）
KEYWORD_ROUTES: dict[str, tuple[str, ...]] = {
    "planning": ("报名", "怎么选", "证书对比", "学习计划", "报考"),
    "quizgen": ("出题", "出一道", "模拟卷", "考我"),
    "practice": ("刷题", "答题", "错题", "模考", "模拟考", "练习"),
}
RULE_CONFIDENCE = 0.7


class RouterDecision(BaseModel):
    """结构化路由判定：意图 + 置信度 + 一句话理由。"""

    intent: Literal["qa", "quizgen", "planning", "practice",
                    "tutor", "smalltalk"] = Field(description="意图标签")
    confidence: float = Field(description="置信度，0 到 1", ge=0.0, le=1.0)
    reason: str = Field(default="", description="一句话判定理由")


_router_model = None


def _get_router_model():
    """结构化路由模型（fast 档，懒初始化单例，绑定 RouterDecision 输出）。

    method="function_calling"：OpenAI 兼容端点的工具调用协议生成结构化输出
    （json_schema 的 Structured Outputs API 兼容端未必支持）。
    """
    global _router_model
    if _router_model is None:
        _router_model = make_model(
            settings.fast_model, settings.fast_base_url,
            settings.llm_api_key).with_structured_output(
                RouterDecision, method="function_calling")
    return _router_model


def _keyword_intent(text: str) -> str | None:
    for intent, keywords in KEYWORD_ROUTES.items():
        if any(k in text for k in keywords):
            return intent
    return None


def classify_intent(state: MainState) -> dict:
    """两级路由：规则快路径直通；未命中（或疑似复合请求）走结构化 LLM 路由。"""
    text = str(state["messages"][-1]["content"]) if state["messages"] else ""
    if not text.strip():
        return {"intent": "smalltalk", "intent_confidence": 0.9}
    composite = any(s in text for s in COMPOSITE_SIGNALS)
    if not composite and (intent := _keyword_intent(text)):
        return {"intent": intent, "intent_confidence": RULE_CONFIDENCE}
    try:
        decision = cast(RouterDecision, _get_router_model().invoke(
            [HumanMessage(content=ROUTER_PROMPT.format(text=text))],
            temperature=0.1,
        ))
        intent = decision.intent
        confidence = decision.confidence
    except Exception:  # noqa: BLE001 — 路由失败兜底 qa（原 P1 行为）；
        # 不再走低置信改道：路由 LLM 都失败时导师（更重的 LLM 链路）大概率也不可用
        return {"intent": "qa", "intent_confidence": 0.5}
    if intent not in LLM_ROUTABLE:
        intent = "qa"
    # 低置信的开放式消息交给导师（tutor 是柔性处理者，smalltalk 除外）
    if confidence < settings.route_confidence_min and intent != "smalltalk":
        intent = "tutor"
    return {"intent": intent, "intent_confidence": round(confidence, 2)}


def route(state: MainState) -> str:
    # smalltalk 有专属节点但不在 REGISTERED（无适配器），其余须已登记
    intent = state["intent"]
    return (
        intent if intent == "smalltalk" or intent in REGISTERED else "fallback_notice"
    )
