"""quizgen 门闸链单测（mock 数据库与 LLM，无外部依赖）。

覆盖：QuestionDraft 载体、并行生成（W1）、GroundingGate 逐字定位判定、
DedupeGate 查重、QualityGate 质量分门槛与打分失败兜底（W2 起只打分不插库）、
AdversarialGate 双 persona 攻击与回退开关（W2）。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from app.llm import llm_client
from app.config import settings
from app.graphs.quizgen.graph import (
    AdversarialGate,
    DedupeGate,
    GroundingGate,
    QualityGate,
    QuestionDraft,
    generate_drafts,
)
from app.services.repositories import ChunkRef


def draft(**kw) -> QuestionDraft:
    base = dict(point_id="T1.1", point_title="第一章 / 卧推",
                question_type="single", stem="卧推的主要目标肌群是？",
                options={"A": "胸大肌", "B": "肱二头肌"}, answer="A",
                evidence_text="杠铃卧推的目标肌群为胸大肌",
                source_chunk_ids=["doc-x-1"])
    base.update(kw)
    return QuestionDraft(**base)


class _FakeConn:
    def __init__(self, dup_id: str | None):
        self._dup_id = dup_id

    def execute(self, *_a, **_k):
        row = (self._dup_id,) if self._dup_id else None
        result = mock.Mock()
        result.first.return_value = row
        return result


def _fake_engine(dup_id: str | None = None) -> mock.MagicMock:
    eng = mock.MagicMock()
    conn = _FakeConn(dup_id)
    eng.begin.return_value.__enter__.return_value = conn
    return eng


class TestGroundingGate(unittest.TestCase):
    def setUp(self):
        self.gate = GroundingGate(mock.MagicMock())

    def _patch_contents(self, content: str):
        return mock.patch("app.graphs.quizgen.graph.repo.chunks_by_ids",
                          return_value={"doc-x-1": ChunkRef(17, content)})

    def test_verbatim_evidence_passes(self):
        with self._patch_contents("……杠铃卧推的目标肌群为胸大肌，动作中保持肩胛稳定……"):
            passed, rejected = self.gate.filter([draft()])
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])
        self.assertGreaterEqual(passed[0].grounding_score, settings.evidence_min_similarity)

    def test_paraphrase_rejected(self):
        with self._patch_contents("深蹲主要发展股四头肌与臀大肌"):
            passed, rejected = self.gate.filter([draft()])
        self.assertEqual(passed, [])
        self.assertIn("grounding", rejected[0]["reason"])

    def test_generation_error_short_circuits(self):
        with self._patch_contents("任意内容"):
            passed, rejected = self.gate.filter([draft(error="no_corpus")])
        self.assertEqual(passed, [])
        self.assertIn("生成失败", rejected[0]["reason"])

    def test_missing_chunk_counts_as_zero(self):
        with mock.patch("app.graphs.quizgen.graph.repo.chunks_by_ids",
                        return_value={}):  # 引用的 chunk 不存在
            passed, rejected = self.gate.filter([draft()])
        self.assertEqual(passed, [])
        self.assertIn("grounding 0.00", rejected[0]["reason"])


class TestDedupeGate(unittest.TestCase):
    def test_no_duplicate_passes(self):
        passed, rejected = DedupeGate(_fake_engine(dup_id=None)).filter([draft()])
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])

    def test_duplicate_rejected_with_reason(self):
        passed, rejected = DedupeGate(_fake_engine(dup_id="q-existing1")).filter([draft()])
        self.assertEqual(passed, [])
        self.assertIn("q-existing1", rejected[0]["reason"])


class TestQualityGate(unittest.TestCase):
    def setUp(self):
        self.gate = QualityGate(mock.MagicMock())

    def test_high_score_passes_scoring_without_insert(self):
        # W2 起 quality 只打分：通过≠入库（question_id 由 adversarial 通过后分配）
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"scores": [4.6]}):
            passed, rejected = self.gate.filter([draft()], cert_id="nsca_cpt")
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])
        d = passed[0]
        self.assertTrue(d.verified)
        self.assertEqual(d.quality_score, 4.6)
        self.assertEqual(d.question_id, "")

    def test_low_score_rejected_not_inserted(self):
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"scores": [3.2]}):
            passed, rejected = self.gate.filter([draft()], cert_id="nsca_cpt")
        self.assertEqual(passed, [])
        self.assertIn("质量分 3.2", rejected[0]["reason"])

    def test_scoring_failure_falls_back_below_gate(self):
        # 打分失败按 3.5 处理：低于 4.0 门槛 → 进人工队列路径
        with mock.patch.object(llm_client, "chat_json",
                               side_effect=ValueError("no json object")):
            passed, rejected = self.gate.filter([draft()], cert_id="nsca_cpt")
        self.assertEqual(passed, [])
        self.assertIn("3.5", rejected[0]["reason"])

    def test_missing_scores_use_fallback_per_item(self):
        with mock.patch.object(llm_client, "chat_json", return_value={"scores": [5.0]}):
            passed, rejected = self.gate.filter([draft(), draft(stem="第二题")],
                                             cert_id="nsca_cpt")
        self.assertEqual(len(passed), 1)   # 第一题 5.0 过闸
        self.assertEqual(len(rejected), 1)  # 第二题缺分 → 3.5 兜底被拒

    def test_empty_drafts_noop(self):
        passed, rejected = self.gate.filter([], cert_id="nsca_cpt")
        self.assertEqual((passed, rejected), ([], []))


class TestAdversarialGate(unittest.TestCase):
    """双 persona 攻击：较真考生（quote 逐字校验）+ 蒙题考生（判断题豁免）。"""

    def setUp(self):
        self.gate = AdversarialGate(mock.MagicMock())

    def _llm(self, *responses):
        return mock.patch.object(llm_client, "chat_json",
                                 side_effect=list(responses))

    def test_nitpick_valid_complaint_rejects(self):
        # 投诉引用了选项原文（"肱二头肌"在选项 B 中）且 severity 达标 → 拒绝
        with self._llm({"complaints": [{"q": 1, "option": "B",
                                        "quote": "肱二头肌",
                                        "reason": "题干未限定动作细节，B 也可论证",
                                        "severity": 4}]},
                       {"guesses": []}):
            passed, rejected = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(passed, [])
        self.assertIn("较真考生", rejected[0]["reason"])

    def test_nitpick_quote_not_in_options_ignored(self):
        # 编造的投诉（quote 定位不到选项原文）无效 → 放行
        with self._llm({"complaints": [{"q": 1, "option": "B",
                                        "quote": "选项里根本没有这段话",
                                        "reason": "x", "severity": 5}]},
                       {"guesses": []}):
            passed, rejected = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])

    def test_low_severity_complaint_ignored(self):
        with self._llm({"complaints": [{"q": 1, "option": "A",
                                        "quote": "胸大肌",
                                        "reason": "表述略啰嗦", "severity": 2}]},
                       {"guesses": []}):
            passed, rejected = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)

    def test_guesser_hits_answer_rejects(self):
        # 不看题干猜对标答且高置信 → 可猜测 → 拒绝
        with self._llm({"complaints": []},
                       {"guesses": [{"q": 1, "pick": "A",
                                     "strategy": "最长且最专业的表述", "confidence": 5}]}):
            passed, rejected = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(passed, [])
        self.assertIn("蒙题测试命中", rejected[0]["reason"])

    def test_guesser_low_confidence_passes(self):
        with self._llm({"complaints": []},
                       {"guesses": [{"q": 1, "pick": "A", "strategy": "蒙",
                                     "confidence": 3}]}):
            passed, _ = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)

    def test_guesser_wrong_pick_passes(self):
        with self._llm({"complaints": []},
                       {"guesses": [{"q": 1, "pick": "B", "strategy": "蒙",
                                     "confidence": 5}]}):
            passed, _ = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)

    def test_judge_exempt_from_guesser(self):
        # 判断题天然可猜：只发较真考生一次调用，蒙题考生不参与
        judge = draft(question_type="judge", options={"A": "对", "B": "错"})
        with mock.patch.object(llm_client, "chat_json",
                               return_value={"complaints": []}) as m:
            passed, _ = self.gate.filter([judge], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)
        self.assertEqual(m.call_count, 1)

    def test_llm_failure_fail_open(self):
        # 对抗缺席 fail-open：前三道闸仍在，本闸不阻塞管线
        with mock.patch.object(llm_client, "chat_json",
                               side_effect=ValueError("no json object")):
            passed, rejected = self.gate.filter([draft()], "nsca_cpt", insert=False)
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])

    def test_disabled_pass_through_and_inserts(self):
        # 开关关闭 = 行为与旧闸门链完全一致：全数放行并入库
        with mock.patch.object(settings, "adversarial_gate_enabled", False), \
             mock.patch("app.graphs.quizgen.graph.insert_question") as ins, \
             mock.patch.object(llm_client, "chat_json") as m:
            passed, rejected = self.gate.filter([draft()], "nsca_cpt")
        self.assertEqual(len(passed), 1)
        self.assertEqual(rejected, [])
        ins.assert_called_once()
        m.assert_not_called()

    def test_survivor_inserted_with_question_id(self):
        with self._llm({"complaints": []}, {"guesses": []}), \
             mock.patch("app.graphs.quizgen.graph.insert_question") as ins:
            passed, _ = self.gate.filter([draft()], "nsca_cpt")
        self.assertTrue(passed[0].question_id.startswith("q-"))
        ins.assert_called_once()


class TestGenerateDraftsParallel(unittest.TestCase):
    """W1 并行生成：结果按考点原序组装，题型轮换确定性不因并行改变。"""

    POINTS = [{"id": f"P{i}", "chapter": f"第{i}章", "title": f"考点{i}"}
              for i in range(1, 5)]

    @staticmethod
    def _fake_llm(prompt, **_kw):
        # 按 prompt 里的考点与题型回显，用于断言顺序与轮换
        content = prompt[1]["content"]
        title = content.split("考点：", 1)[1].splitlines()[0]
        qtype = content.split("题型：", 1)[1].splitlines()[0]
        return {"type": qtype, "stem": f"题-{title}", "answer": "A",
                "options": {"A": "x", "B": "y"}, "explanation": "e",
                "evidence_text": "ev", "source_chunk_ids": ["doc-x-1"],
                "difficulty": 3}

    def _run(self, workers: int) -> list[QuestionDraft]:
        cand = SimpleNamespace(chunk_id="doc-x-1", content="材料内容")
        with mock.patch.object(settings, "quizgen_parallel_workers", workers), \
             mock.patch("app.graphs.quizgen.graph.searcher") as s, \
             mock.patch.object(llm_client, "chat_json",
                               side_effect=self._fake_llm):
            s.search.return_value = [cand]
            state = generate_drafts({"exam_points": self.POINTS})
        return state["drafts"]

    def test_parallel_preserves_order_and_rotation(self):
        for workers in (1, 4):
            with self.subTest(workers=workers):
                drafts = self._run(workers)
                self.assertEqual([d.point_id for d in drafts],
                                 ["P1", "P2", "P3", "P4"])
                self.assertEqual([d.question_type for d in drafts],
                                 ["single", "judge", "multi", "single"])
                self.assertEqual([d.stem for d in drafts],
                                 [f"题-第{i}章 / 考点{i}" for i in range(1, 5)])

    def test_parallel_error_isolation(self):
        # 某考点检索空手只影响该考点（error 草稿），不拖垮整批
        cand = SimpleNamespace(chunk_id="doc-x-1", content="材料内容")

        def fake_search(query, **_kw):
            return [] if "考点2" in query else [cand]

        with mock.patch.object(settings, "quizgen_parallel_workers", 4), \
             mock.patch("app.graphs.quizgen.graph.searcher") as s, \
             mock.patch.object(llm_client, "chat_json",
                               side_effect=self._fake_llm):
            s.search.side_effect = fake_search
            drafts = generate_drafts({"exam_points": self.POINTS})["drafts"]
        self.assertEqual(drafts[1].error, "no_corpus")
        self.assertEqual([d.error == "" for d in drafts],
                         [True, False, True, True])


if __name__ == "__main__":
    unittest.main()


class SelfContainedGateTest(unittest.TestCase):
    """闸门0：题干悬空引用（根据表13.3/如图/见下表）直接拒绝。"""

    def test_dangling_table_ref_rejected(self):
        from app.graphs.quizgen.graph import self_contained_check
        d = QuestionDraft(point_id="p1", point_title="t",
                          stem="根据表13.3，这种训练体系属于：")
        out = self_contained_check({"drafts": [d]})
        self.assertEqual(len(out["drafts"]), 0)
        self.assertIn("悬空引用", out["rejected"][0]["reason"])

    def test_self_contained_stem_passes(self):
        from app.graphs.quizgen.graph import self_contained_check
        d = QuestionDraft(point_id="p1", point_title="t",
                          stem="先完成一个动作的所有组再开始下一个动作，这属于哪种训练体系？")
        out = self_contained_check({"drafts": [d]})
        self.assertEqual(len(out["drafts"]), 1)
        self.assertEqual(out["rejected"], [])
