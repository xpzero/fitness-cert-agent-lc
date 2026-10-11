"""学情诊断 agent 单测（W3）：工具环行为 + 降级链，mock LLM 与工具。

覆盖 common.build_agent_loop 的环语义（步数上限、未知工具防死循环、
决策失败收尾）与 diagnosis 的收尾合成/规则版兜底。
"""
from __future__ import annotations

import unittest
from unittest import mock

from app.graphs.common import AgentLoopState, build_agent_loop
from app.graphs.diagnosis import graph as diag
from app.llm import llm_client


class _LoopState(AgentLoopState, total=False):
    final_report: dict | None


def _loop(resp_sequence, tools=None, finish=None, max_steps=4):
    finish = finish or (lambda s: {"final_report": {"steps": len(s.get("steps") or [])}})
    tools = tools or {"echo": lambda inp: f"echo:{inp}"}
    g = build_agent_loop(_LoopState, system_prompt="sys", tools=tools,
                         finish_fn=finish, max_steps=max_steps)
    patcher = mock.patch.object(llm_client, "chat_json",
                                side_effect=list(resp_sequence))
    return g, patcher, finish


class TestAgentLoop(unittest.TestCase):
    def _invoke(self, g):
        return g.invoke({"task": "t", "steps": [], "final_report": None})

    def test_two_tool_calls_then_finish(self):
        g, patcher, _ = _loop([
            {"thought": "a", "action": "echo", "action_input": "1"},
            {"thought": "b", "action": "echo", "action_input": "2"},
            {"thought": "done", "action": "finish"},
        ])
        with patcher:
            state = self._invoke(g)
        self.assertEqual(len(state["steps"]), 2)
        self.assertEqual(state["steps"][0]["output"], "echo:1")
        self.assertIsNotNone(state["final_report"])

    def test_unknown_tool_finishes_not_loops(self):
        # 未知工具名 → 直接收尾（不把错误喂回 agent 重试，防死循环）
        g, patcher, _ = _loop([{"thought": "?", "action": "nope",
                                "action_input": {}}])
        with patcher:
            state = self._invoke(g)
        self.assertEqual(state.get("steps"), [])
        self.assertIsNotNone(state["final_report"])

    def test_max_steps_truncates(self):
        g, patcher, _ = _loop([{"action": "echo", "action_input": i}
                               for i in range(10)], max_steps=3)
        with patcher:
            state = self._invoke(g)
        self.assertEqual(len(state["steps"]), 3)
        self.assertIsNotNone(state["final_report"])

    def test_llm_failure_finishes_with_empty_steps(self):
        g, patcher, _ = _loop([ValueError("boom")])
        with patcher:
            state = self._invoke(g)
        self.assertEqual(state.get("steps"), [])
        self.assertIsNotNone(state["final_report"])

    def test_tool_exception_recorded_and_continues(self):
        def boom(_inp):
            raise RuntimeError("sql down")

        g, patcher, _ = _loop([
            {"action": "boom_tool", "action_input": {}},
            {"action": "finish"},
        ], tools={"boom_tool": boom})
        with patcher:
            state = self._invoke(g)
        self.assertIn("工具执行失败", state["steps"][0]["output"])


class TestDiagnosisFinish(unittest.TestCase):
    def test_synthesize_requires_evidence_fields(self):
        # 合成输出的 findings 结构（评测端按 source_tool 重放核对）
        with mock.patch.object(
                llm_client, "chat_json",
                return_value={"findings": [{"chapter": "第3章",
                                            "symptom": "正确率 40%",
                                            "evidence": {"metric": "正确率",
                                                         "value": "12/30",
                                                         "source_tool": "chapter_accuracy"}}],
                              "suggestions": ["补练"]}), \
             mock.patch("app.graphs.diagnosis.graph.build_diagnosis_tools"):
            finish = diag._make_finish_fn("u1")
            out = finish({"steps": [{"tool": "chapter_accuracy",
                                     "input": None, "thought": "",
                                     "output": "第3章：12/30"}]})
        self.assertFalse(out["degraded"])
        self.assertEqual(out["final_report"]["findings"][0]["evidence"]["source_tool"],
                         "chapter_accuracy")

    def test_empty_steps_degrades_to_rule_report(self):
        with mock.patch.object(
                diag, "build_diagnosis_tools") as bt:
            bt.return_value = {
                "chapter_accuracy": lambda _i: "无答题记录",
                "wrongbook_backlog": lambda _i: "错题本为空"}
            out = diag._make_finish_fn("u1")({"steps": []})
        self.assertTrue(out["degraded"])
        self.assertEqual(len(out["final_report"]["findings"]), 2)

    def test_synthesize_llm_failure_degrades(self):
        with mock.patch.object(llm_client, "chat_json",
                               side_effect=ValueError("no json")), \
             mock.patch.object(diag, "build_diagnosis_tools") as bt:
            bt.return_value = {"chapter_accuracy": lambda _i: "x",
                               "wrongbook_backlog": lambda _i: "y"}
            out = diag._make_finish_fn("u1")(
                {"steps": [{"tool": "chapter_accuracy", "input": None,
                            "thought": "", "output": "o"}]})
        self.assertTrue(out["degraded"])


if __name__ == "__main__":
    unittest.main()
