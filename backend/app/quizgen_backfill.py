"""知识库索引完成后的自动铺题（覆盖驱动）。

document indexed → 投递铺题任务到独立单线程执行器（不占解析 worker 线程）。
任务体与 scripts/batch_generate.py 同一循环逻辑：查未覆盖考点 → quizgen
四闸出题 → 入库；重复失败考点进排除名单防死循环。quizgen 自带语义查重，
重复触发不产生重复题。批量上传时去抖：3 秒收集窗内多个 indexed 合并为
一次铺题。失败只记日志，不影响文档 indexed 状态。
"""
from __future__ import annotations

import logging
import threading
import time

from app.config import settings
from app.db import database

logger = logging.getLogger(__name__)


def _coverage(cert: str) -> tuple[int, int, list[str]]:
    from app.services.repositories import repo

    counts = repo.exam_point_counts(cert)
    covered = sum(1 for r in counts if r["n"])
    return covered, len(counts), [r["id"] for r in counts if not r["n"]]


def run_coverage_backfill(target: int | None = None,
                          rounds: int | None = None) -> dict:
    """铺题主循环（与 batch_generate 脚本同逻辑）：返回 {covered, total, accepted}。"""
    from app.graphs.quizgen.graph import build_quizgen_graph

    cert = settings.default_cert
    target = target or settings.auto_generate_target
    rounds = rounds or settings.auto_generate_rounds
    exclude: list[str] = []
    accepted_total = 0
    for _rnd in range(rounds):
        cov, total, uncovered = _coverage(cert)
        if cov >= target or not uncovered:
            break
        if not exclude:  # 首轮才建图（覆盖已达标时完全不碰 quizgen）
            g = build_quizgen_graph()
        state = g.invoke({"cert_id": cert, "n_points": 4,
                          "exclude_points": exclude})
        accepted_total += len(state.get("accepted") or [])
        if not state.get("coverage_delta"):
            exclude += [p["id"] for p in state.get("exam_points") or []
                        if p["id"] not in state.get("coverage_delta", [])]
        time.sleep(2)
    cov, total, _ = _coverage(cert)
    return {"covered": cov, "total": total, "accepted": accepted_total}


class QuizgenBackfillWorker:
    """单线程执行器 + 去抖收集窗：pending 信号在窗口内合并为一次铺题。"""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def trigger(self) -> None:
        """文档 indexed 后调用：置位信号（去抖窗口后由工作线程消费）。"""
        if not settings.auto_generate_on_ingest:
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name="quizgen-backfill")
                self._thread.start()
        self._event.set()

    def _loop(self) -> None:
        database.init_db()
        while True:
            self._event.wait()
            time.sleep(settings.auto_generate_debounce)  # 收集窗：批量上传合并
            self._event.clear()
            try:
                result = run_coverage_backfill()
                logger.info("自动铺题完成：覆盖 %s/%s，本轮入库 %s 题",
                            result["covered"], result["total"],
                            result["accepted"])
            except Exception as e:  # noqa: BLE001 — 铺题失败不影响文档状态
                logger.warning("自动铺题失败（不影响文档索引）：%s", e)


backfill_worker = QuizgenBackfillWorker()
