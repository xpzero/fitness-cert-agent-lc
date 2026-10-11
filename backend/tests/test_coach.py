"""讲题教练单测（W4）：状态机流转、变式题挂载、超轮强制讲透（mock LLM/DB）。"""
from __future__ import annotations

import unittest
from unittest import mock

from app.config import settings
from app.graphs.quizgen.graph import QuestionDraft
from app.services import coach_service as cs


QUESTION = {"id": "q-1", "cert_id": "nsca_cpt", "type": "single",
            "stem": "卧推的主要目标肌群是？",
            "options": {"A": "胸大肌", "B": "肱二头肌"}, "answer": "A",
            "explanation": "卧推主练胸大肌",
            "source_chunk_ids": ["doc-x-1"], "exam_point_ids": ["T1.1"]}


def _llm(resp: dict):
    return mock.patch.object(cs.llm_client, "chat_json", return_value=resp)


class TestCoachSession(unittest.TestCase):
    def test_start_session_opens_with_probe(self):
        opening = {"reply": "你为什么选 B 呢？说说你的想法。",
                   "next_phase": "probe", "ready_for_variant": False}
        with _llm(opening), \
             mock.patch.object(cs, "_load_question", return_value=QUESTION), \
             mock.patch.object(cs, "_last_user_answer", return_value="B"), \
             mock.patch.object(cs, "get_engine") as eng:
            out = cs.start_session("u1", "q-1")
        self.assertEqual(out["phase"], "probe")
        self.assertIn("你为什么选 B", out["greeting"])
        conn = eng.return_value.begin.return_value.__enter__.return_value
        conn.execute.assert_called_once()  # INSERT coach_sessions

    def test_send_message_attaches_variant_on_verify(self):
        session = {"id": "s1", "user_id": "u1", "question_id": "q-1",
                   "messages": [{"role": "coach", "content": "…"}],
                   "status": "active", "phase": "explain",
                   "variant_question_id": ""}
        ready = {"reply": "好，我们来做道变式题检验。",
                 "next_phase": "verify", "ready_for_variant": True}
        variant = {"id": "q-var1", "type": "single", "stem": "变式：卧推离心阶段主要参与的肌群？",
                   "options": {"A": "胸大肌", "B": "背阔肌"}, "answer": "A",
                   "explanation": "e"}
        with _llm(ready), \
             mock.patch.object(cs, "_get_session", return_value=session), \
             mock.patch.object(cs, "_load_question", return_value=QUESTION), \
             mock.patch.object(cs, "_last_user_answer", return_value="B"), \
             mock.patch.object(cs, "_generate_variant", return_value=variant) as gv, \
             mock.patch.object(cs, "_update_session") as upd:
            out = cs.send_message("s1", "我懂了")
        self.assertEqual(out["phase"], "verify")
        self.assertEqual(out["variant"]["id"], "q-var1")
        self.assertIn("变式：", out["reply"])
        gv.assert_called_once()
        upd.assert_called_once()
        self.assertEqual(upd.call_args.kwargs["variant_id"], "q-var1")

    def test_over_round_forces_explain(self):
        # 超轮后 LLM 仍想留在 probe/hint → 代码强制至少 explain（讲透）
        session = {"id": "s1", "user_id": "u1", "question_id": "q-1",
                   "messages": [{"role": "coach", "content": "…"}] +
                               [{"role": "user", "content": "x"},
                                {"role": "coach", "content": "y"}] *
                               settings.coach_max_rounds,
                   "status": "active", "phase": "hint", "variant_question_id": ""}
        with _llm({"reply": "再想想？", "next_phase": "probe",
                   "ready_for_variant": False}), \
             mock.patch.object(cs, "_get_session", return_value=session), \
             mock.patch.object(cs, "_load_question", return_value=QUESTION), \
             mock.patch.object(cs, "_last_user_answer", return_value="B"), \
             mock.patch.object(cs, "_update_session"):
            out = cs.send_message("s1", "不知道")
        self.assertEqual(out["phase"], "explain")


class _Conn:
    """answer_variant 的 SQL 序列 mock：SELECT wrong_book → 其余 execute。"""

    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(str(sql))
        result = mock.Mock()
        result.first.return_value = (2.5, 1, 1)  # ease, interval, reps
        return result


class TestAnswerVariant(unittest.TestCase):
    def test_correct_answer_updates_origin_sm2_and_closes(self):
        session = {"id": "s1", "user_id": "u1", "question_id": "q-1",
                   "messages": [], "status": "active", "phase": "verify",
                   "variant_question_id": "q-var1"}
        variant_q = dict(QUESTION, id="q-var1")
        conn = _Conn()
        eng = mock.MagicMock()
        eng.begin.return_value.__enter__.return_value = conn
        with mock.patch.object(cs, "_get_session", return_value=session), \
             mock.patch.object(cs, "_load_question", return_value=variant_q), \
             mock.patch.object(cs, "get_engine", return_value=eng), \
             mock.patch.object(cs, "_update_session") as upd:
            out = cs.answer_variant("s1", "A")
        self.assertTrue(out["correct"])
        self.assertTrue(out["sm2_updated"])
        self.assertIn("复习间隔已拉长", out["closing"])
        # SQL 序列：读原题 SM-2 → 更新原题 → 记答题历史
        joined = "\n".join(conn.executed)
        self.assertIn("UPDATE wrong_book", joined)
        self.assertIn("INSERT INTO user_answers", joined)
        upd.assert_called_once()
        self.assertEqual(upd.call_args.kwargs["status"], "done")

    def test_wrong_answer_adds_variant_to_wrongbook(self):
        session = {"id": "s1", "user_id": "u1", "question_id": "q-1",
                   "messages": [], "status": "active", "phase": "verify",
                   "variant_question_id": "q-var1"}
        variant_q = dict(QUESTION, id="q-var1")
        conn = _Conn()
        eng = mock.MagicMock()
        eng.begin.return_value.__enter__.return_value = conn
        with mock.patch.object(cs, "_get_session", return_value=session), \
             mock.patch.object(cs, "_load_question", return_value=variant_q), \
             mock.patch.object(cs, "get_engine", return_value=eng), \
             mock.patch.object(cs, "_update_session"):
            out = cs.answer_variant("s1", "B")
        self.assertFalse(out["correct"])
        self.assertIn("INSERT INTO wrong_book", "\n".join(conn.executed))


class TestVariantDraft(unittest.TestCase):
    def test_generate_variant_reads_accepted_first(self):
        draft = QuestionDraft(point_id="T1.1", point_title="t",
                              question_type="single", stem="变式题",
                              options={"A": "x"}, answer="A",
                              question_id="q-var9")
        fake_graph = mock.MagicMock()
        fake_graph.invoke.return_value = {"accepted": [draft]}
        with mock.patch("app.graphs.quizgen.graph.build_quizgen_graph",
                        return_value=fake_graph) as bg:
            variant = cs._generate_variant(QUESTION)
        self.assertEqual(variant["id"], "q-var9")
        # seed_points 必须带原题考点（定向出题）
        self.assertEqual(bg.call_args.args[0] if bg.call_args.args else None, None)
        state = fake_graph.invoke.call_args.args[0]
        self.assertEqual(state["seed_points"], ["T1.1"])

    def test_generate_variant_all_rejected_returns_none(self):
        fake_graph = mock.MagicMock()
        fake_graph.invoke.return_value = {"accepted": []}
        with mock.patch("app.graphs.quizgen.graph.build_quizgen_graph",
                        return_value=fake_graph):
            self.assertIsNone(cs._generate_variant(QUESTION))


if __name__ == "__main__":
    unittest.main()
