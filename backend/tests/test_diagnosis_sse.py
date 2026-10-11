"""SSE 学情诊断消费循环单测：原生 updates 流 → 旧版 step/report 事件格式。"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from app.api.routes.quiz import _diagnosis_events
from app.graphs.native import messages_to_steps
from tests._fake_model import ScriptedToolCallModel


def _run(graph, user_id="u1", cert_id=""):
    return asyncio.run(_collect(graph, user_id, cert_id))


async def _collect(graph, user_id, cert_id):
    events = []
    async for ev in _diagnosis_events(graph, user_id, cert_id):
        events.append(ev)
    return events


def _fake_report(**over):
    base = {"findings": [{"chapter": "第3章", "symptom": "正确率 40%",
                          "evidence": {"metric": "正确率", "value": "12/30",
                                       "source_tool": "chapter_accuracy"}}],
            "suggestions": ["补练"], "steps_trace": [],
            "degraded": False, "plan_adjusted": False}
    base.update(over)
    return base


class TestDiagnosisSSEEvents(unittest.TestCase):
    def _graph(self):
        import app.graphs.diagnosis.graph as dg
        from langchain_core.messages import AIMessage

        model = ScriptedToolCallModel([
            AIMessage(content="", tool_calls=[
                {"name": "chapter_accuracy", "args": {}, "id": "c1"}]),
            AIMessage(content="再看错题本", tool_calls=[
                {"name": "wrongbook_backlog", "args": {}, "id": "c2"}]),
            AIMessage(content="调查完毕"),
        ])
        with mock.patch.object(dg, "make_model", return_value=model):
            return dg.build_diagnosis_graph("u1", "")

    def test_step_events_match_legacy_format(self):
        with mock.patch(
                "app.graphs.diagnosis.graph.finalize_report",
                side_effect=lambda state, u, c="": _fake_report()) as fr:
            events = _run(self._graph())
        # 事件序列：step × 2 → report（旧版无中间帧）
        self.assertEqual([e["event"] for e in events],
                         ["step", "step", "report"])
        s1, s2 = events[0], events[1]
        # 旧版 step 帧字段：tool / thought / output（+input，前端容错忽略）
        self.assertEqual(s1["tool"], "chapter_accuracy")
        self.assertEqual(s1["thought"], "")
        self.assertIn("output", s1)
        self.assertEqual(s2["tool"], "wrongbook_backlog")
        self.assertEqual(s2["thought"], "再看错题本")
        # report 帧原样透传 finalize_report 的返回
        self.assertEqual(events[2]["report"]["findings"][0]["chapter"], "第3章")
        self.assertEqual(fr.call_count, 1)

    def test_report_event_uses_final_state(self):
        # synthesize 产出的 final_report 进入 finalize（plan_adjust 应用等）
        import app.graphs.diagnosis.graph as dg

        with mock.patch.object(dg, "finalize_report",
                               side_effect=lambda state, u, c="":
                               _fake_report(degraded=state.get("degraded"))):
            events = _run(self._graph())
        self.assertFalse(events[-1]["report"]["degraded"])

    def test_no_tool_calls_single_report(self):
        # 环内零工具调用（模型直接回答）：无 step 帧，只有 report
        import app.graphs.diagnosis.graph as dg
        from langchain_core.messages import AIMessage

        model = ScriptedToolCallModel([AIMessage(content="直接答")])
        with mock.patch.object(dg, "make_model", return_value=model), \
             mock.patch.object(dg, "finalize_report",
                               side_effect=lambda s, u, c="": _fake_report()):
            events = _run(dg.build_diagnosis_graph("u1", ""))
        self.assertEqual([e["event"] for e in events], ["report"])

    def test_step_json_serializable(self):
        # SSE 帧最终走 json.dumps：step 字段必须可序列化
        with mock.patch(
                "app.graphs.diagnosis.graph.finalize_report",
                side_effect=lambda s, u, c="": _fake_report()):
            events = _run(self._graph())
        for ev in events:
            json.dumps(ev, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
