"""规划驾驶舱的纯计算部分（无 IO，可单测）。"""
from __future__ import annotations

import re
from datetime import date, timedelta

# 当前阶段无 daily_tasks 时的兜底任务
FALLBACK_TASKS = ["阅读当前阶段章节", "每日 10 题练习", "错题复习"]


def count_weekend_days(today: date, days_left: int) -> int:
    """有效学习日参考：剩余天数中落在周末的天数（便于用户自行安排）。"""
    return sum(1 for i in range(days_left) if (today + timedelta(days=i)).weekday() >= 5)


def current_streak(answer_days: list[date], today: date) -> int:
    """从今天往回数的连续刷题天数（answer_days 需按日期倒序）。"""
    streak = 0
    for i, d in enumerate(answer_days):
        if d == today - timedelta(days=i):
            streak += 1
        else:
            break
    return streak


def plan_start_date(plan_id: str, today: date) -> date:
    """计划起始日：从计划 id 内嵌日期解析（id 形如 plan-xxxx2026-10-06）；
    解析失败回退今天（save_plan 的 id 生成规则与之配套）。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", plan_id)
    return date.fromisoformat(m.group(1)) if m else today


def week_number(start: date, today: date) -> int:
    return max(1, (today - start).days // 7 + 1)


def find_current_phase(phases: list[dict], week_no: int) -> dict | None:
    """按周数定位当前阶段，附 _span/_progress/_cur_week 计算字段（返回前剔除）。"""
    elapsed_weeks = 0
    for ph in phases:
        week_nums = re.findall(r"\d+", str(ph.get("weeks", "")))
        span = max(1, (int(week_nums[1]) - int(week_nums[0]) + 1)) if len(week_nums) >= 2 else 1
        if elapsed_weeks + span >= week_no or ph is phases[-1]:
            return {**ph, "_span": span,
                    "_progress": min(100, int((week_no - elapsed_weeks) / span * 100)),
                    "_cur_week": week_no - elapsed_weeks}
        elapsed_weeks += span
    return None


def split_week_tasks(daily_tasks: str, limit: int = 6) -> list[str]:
    """当前阶段 daily_tasks 按中/英分号拆分为本周任务（【模考后加练】由前端标红）。"""
    tasks = [t.strip() for t in re.split(r"[；;]", str(daily_tasks)) if t.strip()][:limit]
    return tasks or FALLBACK_TASKS


def overview_response(*, plan: dict, plan_id: str, exam_date, today: date,
                      coverage_totals: tuple[int, int], answered_count: int,
                      mock_trend: list[float], answer_days: list[date],
                      checkins: dict) -> dict:
    """组装 /plan/overview 响应（所有输入为已查好的数据，输出结构保持前端契约）。"""
    parsed_exam_date = (exam_date if isinstance(exam_date, date)
                        else date.fromisoformat(str(exam_date)))
    days_left = (parsed_exam_date - today).days
    week_no = week_number(plan_start_date(plan_id, today), today)
    phases = plan.get("phases", [])
    current_phase = find_current_phase(phases, week_no)
    covered, total = coverage_totals
    trend_delta = (mock_trend[0] - mock_trend[1]) if len(mock_trend) >= 2 else None
    return {"active": True, "exam_date": str(parsed_exam_date),
            "days_left": days_left,
            "weekend_days": count_weekend_days(today, days_left), "week_no": week_no,
            "weekly_hours": plan.get("weekly_hours"),
            "coverage": {"covered": covered, "total": total,
                         "pct": round(covered / max(1, total) * 100)},
            "answered": answered_count, "streak": current_streak(answer_days, today),
            "mock_trend": mock_trend, "trend_delta": trend_delta,
            "phases": [{k: v for k, v in ph.items() if not k.startswith("_")}
                       for ph in phases],
            "current_phase": dict(current_phase or {}),
            "week_tasks": split_week_tasks(
                (current_phase or {}).get("daily_tasks", "")),
            "checkins": checkins, "adjustments": plan.get("adjustments", [])}
