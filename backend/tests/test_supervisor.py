"""supervisor 主图单测：意图路由 + 子图适配器（stub 子图，无外部依赖）。

覆盖：classify_intent 两级路由（关键词直通 + LLM 路由 mock）、route 的
注册表约束、各适配器的状态映射与输出格式、主图全量组装后的节点拓扑。
"""
from __future__ import annotations

import unittest
from unittest import mock

from app.graphs.quizgen.graph import QuestionDraft
from app.graphs.supervisor import (
    ADAPTERS,
    build_main_graph,
    classify_intent,
    route,
)
from app.graphs.supervisor.adapters import _planning_adapter, _quizgen_adapter
from app.llm import llm_client


def main_state(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}], "user_id": "u1"}


class _StubGraph:
    """替代 compiled 子图：记录调用入参，返回预设 state。"""

    def __init__(self, result: dict):
        self.result = result
        self.calls: list[tuple[dict, object]] = []

    def invoke(self, state: dict, config=None):
        self.calls.append((state, config))
        return self.result


class TestClassifyAndRoute(unittest.TestCase):
    def test_keywords(self):
        cases = {
            "报名怎么选证书": "planning",
            "考我一道": "quizgen",
            "我要刷题": "practice",
            "": "smalltalk",
        }
        for text, intent in cases.items():
            self.assertEqual(classify_intent(main_state(text))["intent"], intent, text)

    def test_non_keyword_goes_llm_router(self):
        # 无关键词命中 → LLM 路由（mock 成 qa，确定性断言；失败兜底见 routing 专测）
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"intent": "qa", "confidence": 0.9}):
            self.assertEqual(
                classify_intent(main_state("卧推的目标肌群是什么"))["intent"], "qa")

    def test_route_unregistered_falls_to_todo(self):
        self.assertEqual(route({**main_state("刷题"), "intent": "practice"}), "fallback_notice")
        self.assertEqual(route({**main_state("怎么选"), "intent": "planning"}), "planning")

    def test_adapters_registry_covers_all_chat_intents(self):
        self.assertEqual(set(ADAPTERS), {"qa", "planning", "quizgen", "tutor"})


class TestPlanningAdapter(unittest.TestCase):
    def _result(self):
        return {
            "plan": {"weeks": 8, "phases": [
                {"name": "① 基础扫盲", "weeks": "第1-2周",
                 "daily_tasks": "每天 1 章 + 10 题", "milestone": "基础章节全覆盖"}]},
            "recommended_path": {"primary": "nsca_cpt", "primary_reason": "性价比最优",
                                 "backup": "acsm_cpt", "backup_reason": "学术背书"},
            "cert_comparison": [{"name": "NSCA-CPT", "issuer": "美国国家体能协会",
                                 "fee_range": "约 2180 元"}],
            "plan_status": "draft", "final": "",
        }

    def test_formats_draft_and_points_to_tab(self):
        stub = _StubGraph(self._result())
        out = _planning_adapter(stub)(main_state("帮我做学习计划"))["subgraph_output"]
        self.assertIn("证书对比", out["final"])
        self.assertIn("性价比最优", out["final"])
        self.assertIn("① 基础扫盲", out["final"])
        self.assertIn("「规划」标签页", out["final"])
        self.assertEqual(out["plan"]["weeks"], 8)

    def test_input_state_and_thread(self):
        stub = _StubGraph(self._result())
        _planning_adapter(stub)(main_state("对比证书"))
        state, config = stub.calls[0]
        self.assertEqual(state["user_id"], "u1")
        self.assertEqual(state["profile"], {})  # 对话内不带 profile → 通用草稿
        self.assertTrue(config["configurable"]["thread_id"].startswith("plan-chat-u1-"))


class TestQuizgenAdapter(unittest.TestCase):
    def _draft(self, **kw) -> QuestionDraft:
        base = dict(point_id="T1.1", point_title="第一章 / 卧推", question_type="single",
                    stem="卧推的主要目标肌群是？", options={"A": "胸大肌", "B": "肱二头肌"},
                    answer="A", explanation="胸大肌是卧推主动肌。",
                    evidence_text="x", source_chunk_ids=["c1"], quality_score=4.5,
                    question_id="q-1", verified=True)
        base.update(kw)
        return QuestionDraft(**base)

    def test_accepted_question_formatted(self):
        stub = _StubGraph({"accepted": [self._draft()], "rejected": [
            {"stem": "s", "reason": "grounding 0.1 < 0.9"}]})
        out = _quizgen_adapter(stub)(main_state("考我一道"))["subgraph_output"]
        self.assertIn("卧推的主要目标肌群是？", out["final"])
        self.assertIn("答案：A", out["final"])
        # 闸门拒绝是建设过程：只进日志，不进用户文案（第 5 课调整）
        self.assertNotIn("未过闸", out["final"])
        self.assertEqual(out["questions"][0]["stem"], "卧推的主要目标肌群是？")  # 结构化透传

    def test_all_rejected_message(self):
        # 选中了考点但全被拒：文案走"未过质量闸"分支，且带 exclude 重试一次
        stub = _StubGraph({"exam_points": [{"id": "T1.1", "title": "卧推", "chapter": "一"}],
                           "accepted": [], "rejected": [{"stem": "s", "reason": "r"}]})
        out = _quizgen_adapter(stub)(main_state("出一道题"))["subgraph_output"]
        self.assertIn("未通过质量闸", out["final"])
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(stub.calls[1][0]["exclude_points"], ["T1.1"])
        self.assertEqual(out["questions"], [])

    def test_n_points_mock_vs_single(self):
        # "考我"生成 2 道由闸门筛（单道会确定性卡死在弱考点）；模拟卷 3 道
        stub = _StubGraph({"accepted": [], "rejected": []})
        adapter = _quizgen_adapter(stub)
        adapter(main_state("考我一道"))
        self.assertEqual(stub.calls[-1][0]["n_points"], 2)
        adapter(main_state("给我出一份模拟卷"))
        self.assertEqual(stub.calls[-1][0]["n_points"], 3)


class TestMainGraphComposition(unittest.TestCase):
    def test_all_nodes_mounted(self):
        from app.graphs.planning.graph import build_planning_graph
        from app.graphs.qa.graph import build_qa_graph
        from app.graphs.quizgen.graph import build_quizgen_graph
        from langgraph.checkpoint.memory import InMemorySaver

        g = build_main_graph({
            "qa": build_qa_graph(),
            "planning": build_planning_graph(checkpointer=InMemorySaver()),
            "quizgen": build_quizgen_graph(),
        })
        self.assertTrue(
            {"classify", "smalltalk", "fallback_notice", "qa", "planning", "quizgen"}
            <= set(g.nodes))

    def test_end_to_end_routes_to_stub_subgraph(self):
        stub = _StubGraph({"final_answer": "胸大肌是卧推的主要肌群。",
                           "refused": False,
                           "cited_chunk_ids": [], "candidates": []})
        g = build_main_graph({"qa": stub})
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"intent": "qa", "confidence": 0.9}):
            result = g.invoke(main_state("卧推的目标肌群是什么？"))
        self.assertIn("胸大肌", result["subgraph_output"]["final"])
        self.assertEqual(len(stub.calls), 1)

    def test_practice_intent_hits_todo(self):
        g = build_main_graph({})
        result = g.invoke(main_state("我要刷题"))
        self.assertIn("「刷题」标签页", result["subgraph_output"]["final"])


if __name__ == "__main__":
    unittest.main()
