"""规划驾驶舱纯计算（app/services/plan_stats.py）单测。"""
from __future__ import annotations

import unittest
from datetime import date

from app.services.plan_stats import (FALLBACK_TASKS, count_weekend_days,
                                     current_streak, find_current_phase,
                                     overview_response, plan_start_date,
                                     split_week_tasks, week_number)

TODAY = date(2026, 10, 7)  # 周三


class TestWeekendDays(unittest.TestCase):
    def test_zero_days_left(self):
        self.assertEqual(count_weekend_days(TODAY, 0), 0)

    def test_spans_one_weekend(self):
        # 周三起 5 天：周四五(工作日) + 六日(2天周末) + 周一
        self.assertEqual(count_weekend_days(TODAY, 5), 2)


class TestStreak(unittest.TestCase):
    def test_consecutive_ending_today(self):
        days = [TODAY, date(2026, 10, 6), date(2026, 10, 5)]
        self.assertEqual(current_streak(days, TODAY), 3)

    def test_gap_breaks_streak(self):
        days = [TODAY, date(2026, 10, 4)]  # 少了 10-06
        self.assertEqual(current_streak(days, TODAY), 1)

    def test_empty(self):
        self.assertEqual(current_streak([], TODAY), 0)


class TestWeekNumber(unittest.TestCase):
    def test_start_day_is_week_1(self):
        self.assertEqual(week_number(TODAY, TODAY), 1)

    def test_10_days_later_is_week_2(self):
        self.assertEqual(week_number(TODAY, date(2026, 10, 17)), 2)


class TestPlanStartDate(unittest.TestCase):
    def test_parses_embedded_date(self):
        self.assertEqual(plan_start_date("plan-xpzero2026-10-01", TODAY),
                         date(2026, 10, 1))

    def test_falls_back_to_today(self):
        self.assertEqual(plan_start_date("plan-abcdef", TODAY), TODAY)


class TestCurrentPhase(unittest.TestCase):
    PHASES = [
        {"name": "① 基础扫盲", "weeks": "第1-2周"},
        {"name": "② 强化刷题", "weeks": "第3-5周"},
        {"name": "③ 模考冲刺", "weeks": "第6-7周"},
    ]

    def test_first_phase(self):
        cur = find_current_phase(self.PHASES, 1)
        self.assertEqual(cur["name"], "① 基础扫盲")
        self.assertEqual(cur["_span"], 2)
        self.assertEqual(cur["_cur_week"], 1)

    def test_mid_phase_progress(self):
        cur = find_current_phase(self.PHASES, 4)  # 第二阶段第 2 周（跨度 3）
        self.assertEqual(cur["name"], "② 强化刷题")
        self.assertEqual(cur["_cur_week"], 2)
        self.assertEqual(cur["_progress"], 66)

    def test_overflow_clamps_to_last(self):
        cur = find_current_phase(self.PHASES, 99)
        self.assertEqual(cur["name"], "③ 模考冲刺")

    def test_empty_phases(self):
        self.assertIsNone(find_current_phase([], 1))


class TestWeekTasks(unittest.TestCase):
    def test_split_by_semicolons(self):
        self.assertEqual(split_week_tasks("读书；刷题； 复盘 ", limit=6),
                         ["读书", "刷题", "复盘"])

    def test_fallback_when_empty(self):
        self.assertEqual(split_week_tasks(""), FALLBACK_TASKS)


class TestOverviewResponse(unittest.TestCase):
    def test_shape_matches_frontend_contract(self):
        out = overview_response(
            plan={"phases": [{"name": "①", "weeks": "第1-2周", "daily_tasks": "a；b"}],
                  "weekly_hours": 10, "adjustments": []},
            plan_id="plan-x2026-10-01", exam_date=date(2026, 10, 21), today=TODAY,
            coverage_totals=(3, 38), answered_count=7,
            mock_trend=[80.0, 60.0], answer_days=[TODAY], checkins={1: True})
        self.assertTrue(out["active"])
        self.assertEqual(out["days_left"], 14)
        self.assertEqual(out["coverage"], {"covered": 3, "total": 38, "pct": 8})
        self.assertEqual(out["streak"], 1)
        self.assertEqual(out["trend_delta"], 20.0)
        self.assertEqual(out["week_tasks"], ["a", "b"])
        # 计算字段不外泄
        self.assertTrue(all(not k.startswith("_") for ph in out["phases"] for k in ph))
        self.assertIn("_progress", out["current_phase"])


if __name__ == "__main__":
    unittest.main()
