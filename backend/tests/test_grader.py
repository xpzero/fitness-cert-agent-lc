import unittest

from app.tools.grader import grade, normalize_answer, resolve_answer_key
from app.tools.grader import GradeResult


class TestNormalize(unittest.TestCase):
    def test_fullwidth_to_halfwidth(self):
        self.assertEqual(normalize_answer("ＡＢＣ"), "ABC")

    def test_multi_sorted_upper(self):
        self.assertEqual(normalize_answer("b a"), "AB")

    def test_whitespace_stripped(self):
        self.assertEqual(normalize_answer(" A、 B "), "AB")


class TestGrade(unittest.TestCase):
    def test_single_correct(self):
        r = grade("single", "A", "A")
        self.assertTrue(r.is_correct)
        self.assertEqual(r.score, 1.0)

    def test_single_wrong_case_insensitive(self):
        self.assertTrue(grade("single", "a", "A").is_correct)

    def test_judge_true_variants(self):
        self.assertTrue(grade("judge", "对", "对").is_correct)
        self.assertFalse(grade("judge", "错", "对").is_correct)

    def test_judge_text_truth_grades_against_letter_answer(self):
        """判断题标准答案存文字（「错」）时，先归一成字母再判分。"""
        opts = {"A": "对", "B": "错"}
        truth = resolve_answer_key("错", opts)
        self.assertTrue(grade("judge", "B", truth).is_correct)
        self.assertFalse(grade("judge", "A", truth).is_correct)


class TestResolveAnswerKey(unittest.TestCase):
    """存量判断题 answer 存选项文字、前端提交字母——判分前需映射到字母键。"""

    def test_judge_text_maps_to_letter(self):
        opts = {"A": "对", "B": "错"}
        self.assertEqual(resolve_answer_key("错", opts), "B")
        self.assertEqual(resolve_answer_key("对", opts), "A")

    def test_option_text_maps_to_letter(self):
        opts = {"A": "同理心", "B": "热诚温暖"}
        self.assertEqual(resolve_answer_key("热诚温暖", opts), "B")

    def test_letter_answer_passthrough(self):
        opts = {"A": "同理心", "B": "热诚温暖", "C": "真挚", "D": "主动倾听"}
        self.assertEqual(resolve_answer_key("A", opts), "A")

    def test_multi_combo_passthrough(self):
        self.assertEqual(resolve_answer_key("ac", {"A": "x", "C": "z"}), "AC")

    def test_no_options_returns_normalized(self):
        self.assertEqual(resolve_answer_key("Ｂ", {}), "B")

    def test_multi_all_correct_out_of_order(self):
        r = grade("multi", "C,A", "A C")
        self.assertTrue(r.is_correct)
        self.assertIn("全对", r.detail)

    def test_multi_partial_is_wrong(self):
        r = grade("multi", "A", "ABC")
        self.assertFalse(r.is_correct)
        self.assertIn("漏选", r.detail)

    def test_multi_extra_is_wrong(self):
        r = grade("multi", "ABD", "AB")
        self.assertFalse(r.is_correct)
        self.assertIn("多选 D", r.detail)

    def test_unsupported_type_raises(self):
        with self.assertRaises(ValueError):
            grade("case", "任意", "任意")

    def test_result_type(self):
        self.assertIsInstance(grade("single", "B", "A"), GradeResult)


if __name__ == "__main__":
    unittest.main()
