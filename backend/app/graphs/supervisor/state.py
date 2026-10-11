"""主图状态：messages 归约器 + MainState（从原 supervisor.py 平铺迁移）。"""
from __future__ import annotations

from typing import Annotated, TypedDict


def merge_messages(left: list, right: list) -> list:
    return (left or []) + (right or [])


class MainState(TypedDict):
    messages: Annotated[list, merge_messages]
    user_id: str
    intent: str  # planning | qa | practice | quizgen | tutor | smalltalk
    intent_confidence: float
    subgraph_output: dict
