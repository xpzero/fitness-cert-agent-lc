"""学情诊断 agent 单测（原生 tool-calling 版）：装配结构 + 收尾合成 + 降级链。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.graphs.diagnosis import graph as diag
from app.graphs.native import messages_to_steps
from app.llm import llm_client


def _tool_msg(name: str, content: str):
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=content, name=name, tool_call_id=f"call_{name}")


class TestMessagesToSteps(unittest.TestCase):
    def test_tool_trajectory_extraction(self):
        from langchain_core.messages import AIMessage, HumanMessage
        msgs = [
            HumanMessage(content="诊断学情"),
            AIMessage(content="先看各章正确率"),
            AIMessage(content="", tool_calls=[
                {"name": "chapter_accuracy", "args": {}, "id": "call_1"}]),
            _tool_msg("chapter_accuracy", "第3章：12/30（正确率 40%）"),
            AIMessage(content="", tool_calls=[
                {"name": "wrongbook_backlog", "args": {}, "id": "call_2"}]),
            _tool_msg("wrongbook_backlog", "错题本共 10 题，今日到期 4 题"),
        ]
        steps = messages_to_steps(msgs)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["tool"], "chapter_accuracy")
        self.assertEqual(steps[0]["thought"], "先看各章正确率")
        self.assertIn("40%", steps[0]["output"])

    def test_no_tools_gives_empty_steps(self):
        from langchain_core.messages import AIMessage, HumanMessage
        steps = messages_to_steps([HumanMessage(content="hi"),
                                   AIMessage(content="直接回答")])
        self.assertEqual(steps, [])


class TestDiagnosisSynthesize(unittest.TestCase):
    def test_synthesize_requires_evidence_fields(self):
        with mock.patch.object(
                llm_client, "chat_json",
                return_value={"findings": [{"chapter": "第3章",
                                            "symptom": "正确率 40%",
                                            "evidence": {"metric": "正确率",
                                                         "value": "12/30",
                                                         "source_tool": "chapter_accuracy"}}],
                              "suggestions": ["补练"]}):
            out = diag.synthesize({
                "user_id": "u1",
                "messages": [_tool_msg("chapter_accuracy", "第3章：12/30")]})
        self.assertFalse(out["degraded"])
        self.assertEqual(out["final_report"]["findings"][0]["evidence"]["source_tool"],
                         "chapter_accuracy")
        self.assertEqual(out["final_report"]["steps_trace"][0]["tool"],
                         "chapter_accuracy")

    def test_empty_steps_degrades_to_rule_report(self):
        with mock.patch.object(diag, "_rule_based_report") as rb:
            rb.return_value = {"findings": [{"x": 1}, {"x": 2}],
                               "degraded": True}
            out = diag.synthesize({"user_id": "u1", "messages": []})
        self.assertTrue(out["degraded"])
        rb.assert_called_once_with("u1")
        self.assertEqual(len(out["final_report"]["findings"]), 2)

    def test_synthesize_llm_failure_degrades(self):
        with mock.patch.object(llm_client, "chat_json",
                               side_effect=ValueError("no json")), \
             mock.patch.object(diag, "_rule_based_report") as rb:
            rb.return_value = {"findings": [], "degraded": True}
            out = diag.synthesize({
                "user_id": "u1",
                "messages": [_tool_msg("chapter_accuracy", "第3章：12/30")]})
        self.assertTrue(out["degraded"])
        rb.assert_called_once_with("u1")


class TestGraphTopology(unittest.TestCase):
    def test_graph_builds_with_native_agent(self):
        g = diag.build_diagnosis_graph("u1", "nsca_cpt")
        nodes = set(g.get_graph().nodes)
        self.assertIn("investigate", nodes)
        self.assertIn("synthesize", nodes)


if __name__ == "__main__":
    unittest.main()
