"""SM-2 间隔重复（设计文档 §4.4 schedule 节点规则）。

答对：reps+1，interval 按 1 → 6 → round(interval*ease) 递进
答错：reps=0，interval=1，ease=max(1.3, ease-0.2)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

MIN_EASE = 1.3


@dataclass
class Sm2Record:
    ease: float = 2.5
    interval_days: int = 0
    reps: int = 0
    due_date: str = ""      # ISO 日期

    @classmethod
    def from_fields(cls, ease: float, interval_days: int, reps: int,
                    due_date: str | date) -> "Sm2Record":
        """从 wrong_book 行的字段构建（调用方不再需要手工拼 dict）。"""
        return cls(ease=ease, interval_days=interval_days, reps=reps,
                   due_date=due_date if isinstance(due_date, str) else due_date.isoformat())


def new_record(today: date | None = None) -> Sm2Record:
    day = today or date.today()
    return Sm2Record(due_date=day.isoformat())  # 新错题当天复习


def review(record: Sm2Record | dict, is_correct: bool,
           today: date | None = None) -> Sm2Record:
    """按答题结果更新排程，返回新记录（不修改入参）。"""
    if isinstance(record, dict):
        record = Sm2Record(**{k: record[k] for k in
                              ("ease", "interval_days", "reps", "due_date") if k in record})
    today = today or date.today()

    if is_correct:
        record.reps += 1
        if record.reps == 1:
            record.interval_days = 1
        elif record.reps == 2:
            record.interval_days = 6
        else:
            record.interval_days = max(1, round(record.interval_days * record.ease))
    else:
        record.reps = 0
        record.interval_days = 1
        record.ease = max(MIN_EASE, record.ease - 0.2)

    record.due_date = (today + timedelta(days=record.interval_days)).isoformat()
    return record


def to_dict(record: Sm2Record) -> dict:
    return asdict(record)


def is_due(record: Sm2Record | dict, today: date | None = None) -> bool:
    due_date_str = record["due_date"] if isinstance(record, dict) else record.due_date
    if not due_date_str:
        return True
    return date.fromisoformat(due_date_str) <= (today or date.today())
