"""Cross-encoder 精排（bge-reranker-v2-m3-int8，ONNX 本地推理）。

两阶段漏斗的第二级：混合检索粗召回 top-N → 精排取 top-K。
rerank_enabled=False 或模型加载失败时恒等返回（粗排结果直出），
检索链路永不因精排故障中断。
"""
from __future__ import annotations

import logging
import threading

from app.config import settings

logger = logging.getLogger(__name__)


class Reranker:
    """懒加载单例（首次调用拉起 ONNX 会话 ~1-2 分钟，之后 24ms/条）。"""

    _instance: "Reranker | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._failed = False

    @classmethod
    def get(cls) -> "Reranker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def _ensure(self):
        if self._model is None and not self._failed:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._model = TextCrossEncoder(settings.rerank_model)
            except Exception as e:  # noqa: BLE001 — 精排缺席不阻塞检索
                self._failed = True
                logger.warning("reranker 加载失败（本次进程内恒等直出）：%s", e)
        return self._model

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        """对每个 doc 打相关分。模型不可用返回空列表（调用方走原序）。"""
        model = self._ensure()
        if model is None or not docs:
            return []
        try:
            return [float(s) for s in model.rerank(query, docs)]
        except Exception:  # noqa: BLE001
            return []


reranker = Reranker.get()
