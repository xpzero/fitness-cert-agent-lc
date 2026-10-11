"""supervisor 两级路由单测：规则快路径直通、结构化 LLM 路由、tutor 兜底。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.config import settings
from app.graphs.supervisor import (
    ADAPTERS,
    build_main_graph,
    classify_intent,
    route,
)
from app.graphs.supervisor import router as supervisor_router
from app.prompts.router import ROUTER_PROMPT


def _state(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}], "user_id": "u1"}


class _FakeRouterModel:
    """结构化路由模型的替身：按预设返回 RouterDecision。"""

    def __init__(self, side_effect=None, **fields):
        self.side_effect = side_effect
        self.fields = fields
        self.calls: list[list] = []

    def invoke(self, messages, config=None, **kw):
        self.calls.append(messages)
        if self.side_effect:
            raise self.side_effect
        return supervisor_router.RouterDecision(**self.fields)


def _patch_router(fake: _FakeRouterModel):
    return mock.patch.object(supervisor_router, "_get_router_model",
                             return_value=fake)


def _decide(**fields) -> _FakeRouterModel:
    base = {"reason": "测试"}
    base.update(fields)
    return _FakeRouterModel(**base)


class TestRuleFastPath(unittest.TestCase):
    """关键词命中直通子图——不发起 LLM 调用（零成本零延迟）。"""

    def test_keywords_route_directly_without_llm(self):
        cases = [("帮我做个学习计划", "planning"), ("出一道题考我", "quizgen"),
                 ("我想刷题", "practice"), ("", "smalltalk")]
        for text, intent in cases:
            with self.subTest(text=text), _patch_router(
                    _decide(intent="qa", confidence=0.9)) as m:
                out = classify_intent(_state(text))
            self.assertEqual(out["intent"], intent)
            m.assert_not_called()


class TestStructuredLLMRouter(unittest.TestCase):
    def _route(self, text, fake: _FakeRouterModel):
        with _patch_router(fake):
            return classify_intent(_state(text))

    def test_router_intent_passthrough(self):
        out = self._route("看看我的薄弱点然后练",
                          _decide(intent="tutor", confidence=0.85))
        self.assertEqual(out["intent"], "tutor")

    def test_router_prompt_contains_user_text(self):
        # 提示词只描述判定规则，不再包含"只输出 JSON"的手写协议
        fake = _decide(intent="qa", confidence=0.95)
        self._route("卧推的目标肌群是什么", fake)
        prompt = str(fake.calls[0][0].content)
        self.assertIn("卧推的目标肌群是什么", prompt)
        self.assertNotIn("只输出 JSON", prompt)

    def test_unknown_intent_falls_back_qa(self):
        # Literal 枚举外的意图由 schema 拦截；代码侧防御式兜底再验一次
        fake = _FakeRouterModel()
        fake.fields = {"intent": "外星意图", "confidence": 0.9}
        with _patch_router(fake):
            out = classify_intent(_state("随便说说"))
        self.assertEqual(out["intent"], "qa")

    def test_low_confidence_goes_tutor(self):
        # 低置信的开放式消息交给导师（柔性处理者）；smalltalk 除外
        out = self._route("嗯嗯那啥", _decide(intent="qa", confidence=0.3))
        self.assertEqual(out["intent"], "tutor")
        out = self._route("哈哈", _decide(intent="smalltalk", confidence=0.3))
        self.assertEqual(out["intent"], "smalltalk")

    def test_llm_failure_falls_back_qa(self):
        out = self._route("讲讲训练计划",
                          _FakeRouterModel(side_effect=ValueError("no tool call")))
        self.assertEqual(out["intent"], "qa")
        self.assertEqual(out["intent_confidence"], 0.5)

    def test_confidence_floor_respected(self):
        with mock.patch.object(settings, "route_confidence_min", 0.9):
            out = self._route("什么是RM", _decide(intent="qa", confidence=0.8))
        self.assertEqual(out["intent"], "tutor")

    def test_decision_schema_fields(self):
        # RouterDecision：intent 枚举 + confidence 区间 + reason
        d = supervisor_router.RouterDecision(intent="qa", confidence=0.9,
                                             reason="知识提问")
        self.assertEqual(d.intent, "qa")
        with self.assertRaises(Exception):
            supervisor_router.RouterDecision(intent="外星意图", confidence=0.9)
        with self.assertRaises(Exception):
            supervisor_router.RouterDecision(intent="qa", confidence=1.5)


class TestRouteAndGraph(unittest.TestCase):
    def test_practice_routes_to_fallback_notice(self):
        self.assertEqual(route({"intent": "practice"}), "fallback_notice")

    def test_tutor_registered(self):
        self.assertIn("tutor", ADAPTERS)
        self.assertEqual(route({"intent": "tutor"}), "tutor")

    def test_main_graph_compiles_with_tutor_placeholder(self):
        g = build_main_graph({"qa": object(), "tutor": None})
        names = g.get_graph().nodes
        self.assertIn("tutor", names)
        self.assertIn("qa", names)


if __name__ == "__main__":
    unittest.main()
