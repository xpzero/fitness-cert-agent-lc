"""客观题确定性判分（零 LLM 调用）。

规则（设计文档 §4.4）：
- 单选/判断：答案归一化后严格相等
- 多选：集合全等才算对（职业资格考试无部分给分）
- 案例题（case）：不在此判分，走 quizgen 的 must_mention 要点覆盖（LLM 批改）
"""
from __future__ import annotations

from dataclasses import dataclass

_FULLWIDTH = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})
_DROP_SEPARATORS = str.maketrans({c: "" for c in "、，,；;｜|"})


def normalize_answer(raw: str) -> str:
    """归一化：全角→半角、去空白与分隔符、选项字母大写（多选按字母序）。"""
    cleaned = (raw or "").translate(_FULLWIDTH).strip()
    cleaned = "".join(cleaned.split()).translate(_DROP_SEPARATORS)
    if cleaned and all(ch.isascii() and ch.isalpha() for ch in cleaned):
        upper = cleaned.upper()
        return "".join(sorted(upper)) if len(upper) > 1 else upper
    return cleaned


def resolve_answer_key(answer: str, options: dict) -> str:
    """把"选项文字"形式的标准答案归一成选项字母键。

    前端提交的作答是选项字母（A/B/AB），而出题侧判断题的 answer 可能存
    文字（「对/错」，quizgen 历史约定）——判分/展示前先按 options 反查映射；
    已是字母或匹配不到选项文字时原样返回（归一化后）。
    """
    norm = normalize_answer(answer)
    for key, val in (options or {}).items():
        if norm == normalize_answer(str(val)):
            return normalize_answer(key)
    return norm


@dataclass
class GradeResult:
    is_correct: bool
    score: float          # 0 或 1
    detail: str           # 判分说明（供前端展示/日志）


def _grade_exact(user_answer: str, answer_key: str) -> GradeResult:
    """单选/判断：归一化后严格相等。"""
    ok = user_answer == answer_key
    return GradeResult(ok, 1.0 if ok else 0.0,
                       f"标准答案 {answer_key}，考生 {user_answer or '(未作答)'}")


def _grade_multi(user_answer: str, answer_key: str) -> GradeResult:
    """多选：集合全等才算对（职业资格考试无部分给分）。"""
    user_set = set(user_answer) if user_answer else set()
    answer_key_set = set(answer_key)
    ok = user_set == answer_key_set
    if ok:
        detail = f"多选全对：{''.join(sorted(answer_key_set))}"
    else:
        missed = "".join(sorted(answer_key_set - user_set))
        extra = "".join(sorted(user_set - answer_key_set))
        parts = []
        if missed:
            parts.append(f"漏选 {missed}")
        if extra:
            parts.append(f"多选 {extra}")
        detail = f"{'、'.join(parts)}（标准答案 {''.join(sorted(answer_key_set))}）"
    return GradeResult(ok, 1.0 if ok else 0.0, detail)


_GRADERS = {"single": _grade_exact, "judge": _grade_exact, "multi": _grade_multi}


def grade(question_type: str, user_answer: str, answer_key: str) -> GradeResult:
    grader = _GRADERS.get((question_type or "").lower())
    if grader is None:
        raise ValueError(f"不支持的题型: {question_type}（case/oral 走要点覆盖批改）")
    return grader(normalize_answer(user_answer), normalize_answer(answer_key))
