"""平凡节点：smalltalk 问候与 practice 引导（不经主图的子图走 fallback_notice）。"""
from __future__ import annotations

from app.graphs.supervisor.state import MainState

FALLBACK_NOTICE_MSG = (
    "刷题/模考请在「刷题」标签页进行（练习 / 错题复习 / 模考）。"
    "对话内已支持：教材溯源问答、证书对比与规划草稿、AI 出题、导师陪跑。"
)


def smalltalk(state: MainState) -> dict:
    return {
        "reply": {
            "text": "你好！我是健身教练考证助教。可以问我教材知识"
            "（例如：卧推的目标肌群是什么）、对比证书与制定学习计划，"
            "或让我出一道题。"
        }
    }


def fallback_notice(state: MainState) -> dict:
    return {"reply": {"text": FALLBACK_NOTICE_MSG}}
