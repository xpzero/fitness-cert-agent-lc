from datetime import date

import unittest

from app.tools.sm2 import Sm2Record, is_due, new_record, review, to_dict


class TestSm2(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 6)

    def test_first_correct_interval_1(self):
        rec = review(new_record(self.today), True, self.today)
        self.assertEqual(rec.reps, 1)
        self.assertEqual(rec.interval_days, 1)
        self.assertEqual(rec.due_date, "2026-10-07")

    def test_second_correct_interval_6(self):
        rec = review(new_record(self.today), True, self.today)
        rec = review(rec, True, self.today)
        self.assertEqual(rec.interval_days, 6)

    def test_third_correct_uses_ease(self):
        rec = Sm2Record(ease=2.5, interval_days=6, reps=2, due_date="")
        rec = review(rec, True, self.today)
        self.assertEqual(rec.interval_days, 15)  # round(6*2.5)

    def test_wrong_resets_and_lowers_ease(self):
        rec = Sm2Record(ease=2.5, interval_days=15, reps=3, due_date="")
        rec = review(rec, False, self.today)
        self.assertEqual(rec.reps, 0)
        self.assertEqual(rec.interval_days, 1)
        self.assertAlmostEqual(rec.ease, 2.3)

    def test_ease_floored_at_1_3(self):
        rec = Sm2Record(ease=1.35, interval_days=1, reps=0, due_date="")
        for _ in range(5):
            rec = review(rec, False, self.today)
        self.assertEqual(rec.ease, 1.3)

    def test_dict_input_accepted(self):
        rec = review(to_dict(new_record(self.today)), True, self.today)
        self.assertEqual(rec.reps, 1)

    def test_is_due(self):
        rec = new_record(self.today)
        self.assertTrue(is_due(rec, self.today))
        rec.due_date = "2026-10-10"
        self.assertFalse(is_due(rec, self.today))


if __name__ == "__main__":
    unittest.main()
