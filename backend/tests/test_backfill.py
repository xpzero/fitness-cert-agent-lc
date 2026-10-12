"""自动铺题单测：停止条件、排除名单累积、开关与失败隔离（mock 覆盖环与图）。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.quizgen_backfill import QuizgenBackfillWorker, run_coverage_backfill


def _no_op_graph_state(points: int = 4):
    return {"accepted": [], "rejected": [], "coverage_delta": [],
            "exam_points": [{"id": f"p{i}"} for i in range(points)]}


class TestRunCoverageBackfill(unittest.TestCase):
    def test_stops_when_target_reached(self):
        with mock.patch("app.quizgen_backfill._coverage",
                        return_value=(24, 30, [])) as cov, \
             mock.patch("app.graphs.quizgen.graph.build_quizgen_graph") as bg:
            out = run_coverage_backfill(target=24, rounds=5)
        self.assertEqual(out["covered"], 24)
        bg.assert_not_called()  # 覆盖已达标 → 不跑 quizgen

    def test_rounds_cap_and_exclude_accumulation(self):
        # 每轮零覆盖 → 本轮考点全进排除名单；轮数上限退出
        fake_graph = mock.MagicMock()
        fake_graph.invoke.return_value = _no_op_graph_state()
        with mock.patch("app.quizgen_backfill._coverage",
                        return_value=(0, 30, ["p"])), \
             mock.patch("app.graphs.quizgen.graph.build_quizgen_graph",
                        return_value=fake_graph):
            run_coverage_backfill(target=24, rounds=3)
        self.assertEqual(fake_graph.invoke.call_count, 3)
        last_args = fake_graph.invoke.call_args[0][0]
        self.assertEqual(len(last_args["exclude_points"]), 12)  # 前两轮全排除 4×2…实际三轮累计 12


class TestWorkerTrigger(unittest.TestCase):
    def test_trigger_respects_disabled(self):
        import app.quizgen_backfill as qb

        w = QuizgenBackfillWorker()
        with mock.patch.object(qb, "settings") as s:
            s.auto_generate_on_ingest = False
            w.trigger()
        self.assertIsNone(w._thread)  # 未启动线程

    def test_failure_isolated(self):
        import app.quizgen_backfill as qb

        w = QuizgenBackfillWorker()
        with mock.patch.object(qb, "settings") as s:
            s.auto_generate_on_ingest = True
            s.auto_generate_debounce = 0.01
            with mock.patch.object(qb, "run_coverage_backfill",
                                   side_effect=RuntimeError("llm down")) as run:
                w.trigger()
                assert w._thread is not None
                w._thread.join(timeout=5)
        run.assert_called_once()  # 失败被吞（记日志），线程存活
        assert w._thread is not None
        self.assertTrue(w._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
