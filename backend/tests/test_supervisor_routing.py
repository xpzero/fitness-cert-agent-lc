"""supervisor 两级路由单测（W5）：规则快路径直通、LLM 路由、tutor 兜底。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.config import settings
from app.graphs.supervisor import (
    ADAPTERS,
    classify_intent,
    route,
    build_main_graph,
)
from app.llm import llm_client


def _state(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}], "user_id": "u1"}


class TestRuleFastPath(unittest.TestCase):
    """关键词命中直通子图——不发起 LLM 调用（零成本零延迟）。"""

    def test_keywords_route_directly_without_llm(self):
        cases = [("帮我做个学习计划", "planning"), ("出一道题考我", "quizgen"),
                 ("我想刷题", "practice"), ("", "smalltalk")]
        for text, intent in cases:
            with self.subTest(text=text), mock.patch.object(
                    llm_client, "chat_json") as m:
                out = classify_intent(_state(text))
            self.assertEqual(out["intent"], intent)
            m.assert_not_called()


class TestLLMRouter(unittest.TestCase):
    def _route(self, text, llm_resp=None, side_effect=None):
        patcher = (mock.patch.object(llm_client, "chat_json",
                                     side_effect=side_effect)
                   if side_effect else
                   mock.patch.object(llm_client, "chat_json",
                                     return_value=llm_resp))
        with patcher:
            return classify_intent(_state(text))

    def test_router_intent_passthrough(self):
        out = self._route("看看我的薄弱点然后练",
                          {"intent": "tutor", "confidence": 0.85})
        self.assertEqual(out["intent"], "tutor")

    def test_unknown_intent_falls_back_qa(self):
        out = self._route("随便说说", {"intent": "外星意图", "confidence": 0.9})
        self.assertEqual(out["intent"], "qa")

    def test_low_confidence_goes_tutor(self):
        # 低置信的开放式消息交给导师（柔性处理者）；smalltalk 除外
        out = self._route("嗯嗯那啥", {"intent": "qa", "confidence": 0.3})
        self.assertEqual(out["intent"], "tutor")
        out = self._route("哈哈", {"intent": "smalltalk", "confidence": 0.3})
        self.assertEqual(out["intent"], "smalltalk")

    def test_llm_failure_falls_back_qa(self):
        out = self._route("讲讲训练计划", side_effect=ValueError("no json"))
        self.assertEqual(out["intent"], "qa")

    def test_confidence_floor_respected(self):
        with mock.patch.object(settings, "route_confidence_min", 0.9):
            out = self._route("什么是RM", {"intent": "qa", "confidence": 0.8})
        self.assertEqual(out["intent"], "tutor")


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
