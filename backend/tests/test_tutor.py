"""导师 agent 单测（原生 tool-calling 版）：装配结构 + 收尾合成 + 全链 fake 模型。"""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from app.graphs.tutor import graph as tutor
from app.llm import llm_client
from tests._fake_model import ScriptedToolCallModel


def _tool_msg(name: str, content: str):
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=content, name=name, tool_call_id=f"call_{name}")


class TestTutorTools(unittest.TestCase):
    def test_tools_are_native_with_schemas(self):
        from app.graphs.tutor.tools import build_tutor_tools

        tools = {t.name: t for t in build_tutor_tools("u1")}
        self.assertEqual(set(tools), {"qa_answer", "generate_quiz", "diagnose",
                                      "plan_state", "plan_adjust"})
        # @tool 定义：参数 schema 自动生成（args 从 dict 变为具名字段）
        self.assertIn("query", tools["qa_answer"].args)
        self.assertIn("topic", tools["generate_quiz"].args)
        self.assertIn("weak_chapters", tools["plan_adjust"].args)

    def test_user_id_closure_bound(self):
        """工具闭包绑定 user_id：diagnose 内部调用诊断图时用绑定值。"""
        captured = {}

        class _FakeGraph:
            def invoke(self, state, config=None):
                captured.update(state)
                return {"final_report": {"findings": [
                    {"chapter": "第3章", "symptom": "正确率 40%"}],
                    "suggestions": ["补练"]}}

        import app.graphs.diagnosis.graph as dg
        with mock.patch.object(dg, "build_diagnosis_graph",
                               return_value=_FakeGraph()):
            tools = {t.name: t for t in tutor.build_tutor_tools("u42")}
            out = tools["diagnose"].invoke({})
        self.assertEqual(captured["user_id"], "u42")  # 闭包绑定的用户
        self.assertIn("第3章", out)
        self.assertIn("补练", out)


class TestTutorSynthesize(unittest.TestCase):
    def test_synthesize_formats_reply_and_trace(self):
        from langchain_core.messages import AIMessage, HumanMessage

        msgs = [HumanMessage(content="帮我看看薄弱点"),
                AIMessage(content="先查学情"),
                AIMessage(content="", tool_calls=[
                    {"name": "diagnose", "args": {}, "id": "c1"}]),
                _tool_msg("diagnose", "发现：第3章：正确率 40%")]
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"reply": "建议先补第3章"}):
            out = tutor.synthesize({"messages": msgs})
        self.assertEqual(out["final_report"]["reply"], "建议先补第3章")
        self.assertEqual(out["final_report"]["steps_trace"],
                         [{"tool": "diagnose"}])
        self.assertEqual(out["steps"][0]["thought"], "先查学情")

    def test_synthesize_llm_failure_fallback_reply(self):
        with mock.patch.object(llm_client, "chat_json",
                               side_effect=ValueError("no json")):
            out = tutor.synthesize({"messages": []})
        self.assertIn("暂时不可用", out["final_report"]["reply"])
        self.assertEqual(out["final_report"]["steps_trace"], [])

    def test_no_tools_still_synthesizes(self):
        # 环内无工具调用：transcript 兜底文案，回复仍可产出
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"reply": "直接回答"}):
            out = tutor.synthesize({"messages": []})
        self.assertEqual(out["final_report"]["reply"], "直接回答")


class TestTutorGraphTopology(unittest.TestCase):
    def test_graph_builds_with_native_agent(self):
        g = tutor.build_tutor_graph("u1")
        nodes = set(g.get_graph().nodes)
        self.assertIn("investigate", nodes)
        self.assertIn("synthesize", nodes)

    def test_tutor_prompt_has_no_json_protocol(self):
        # 原生循环：提示词不再描述 finish/JSON 决策协议
        from app.prompts.router import TUTOR_SYSTEM
        self.assertNotIn("JSON", TUTOR_SYSTEM)
        self.assertNotIn("finish", TUTOR_SYSTEM)


class TestTutorEndToEndFakeModel(unittest.TestCase):
    """ScriptedToolCallModel 驱动原生环：多工具连续调用 + 出环收尾。"""

    def test_run_tutor_multi_tool_loop(self):
        from langchain_core.messages import AIMessage

        model = ScriptedToolCallModel([
            AIMessage(content="", tool_calls=[
                {"name": "diagnose", "args": {}, "id": "c1"}]),
            AIMessage(content="查计划再出题", tool_calls=[
                {"name": "plan_state", "args": {}, "id": "c2"}]),
            AIMessage(content="", tool_calls=[
                {"name": "qa_answer", "args": {"query": "什么是RM"}, "id": "c3"}]),
            AIMessage(content="信息足够，收尾"),
        ])
        with mock.patch.object(
                tutor, "make_model", return_value=model), \
             mock.patch.object(
                llm_client, "chat_json",
                return_value={"reply": "先补第3章，我出了道题给你"}):
            out = tutor.run_tutor("u1", "看看我的薄弱点然后练")
        self.assertEqual(out["reply"], "先补第3章，我出了道题给你")
        self.assertEqual([s["tool"] for s in out["steps_trace"]],
                         ["diagnose", "plan_state", "qa_answer"])

    def test_sse_style_stream_yields_step_updates(self):
        # 与 /quiz/diagnose 同款的 subgraphs updates 消费方式在 tutor 图上也可用
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.tools import tool as lc_tool

        @lc_tool
        def diagnose() -> str:
            """学情诊断"""
            return "发现：无数据"

        model = ScriptedToolCallModel([
            AIMessage(content="", tool_calls=[
                {"name": "diagnose", "args": {}, "id": "c1"}]),
            AIMessage(content="done"),
        ])
        with mock.patch.object(tutor, "make_model", return_value=model), \
             mock.patch.object(tutor, "build_tutor_tools",
                               return_value=[diagnose]):
            graph = tutor.build_tutor_graph("u1")

        async def run():
            events = []
            async for ns, mode, payload in graph.astream(
                    {"messages": [HumanMessage(content="考我")],
                     "user_id": "u1", "steps": [], "final_report": None},
                    stream_mode=["updates"], subgraphs=True):
                if ns and isinstance(payload, dict) and "tools" in payload:
                    events.append(payload["tools"]["messages"])
            return events

        tool_events = asyncio.run(run())
        self.assertEqual(len(tool_events), 1)  # 一次工具调用一批 ToolMessage
        self.assertEqual(tool_events[0][0].name, "diagnose")


if __name__ == "__main__":
    unittest.main()
