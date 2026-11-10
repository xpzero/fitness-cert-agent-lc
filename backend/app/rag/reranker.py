"""Cross-encoder 精排（bge-reranker-v2-m3）：本地 ONNX 或硅基流动 API。

两阶段漏斗的第二级：混合检索粗召回 top-N → 精排取 top-K。
rerank_enabled=False 或后端失败时恒等返回（粗排结果直出），
检索链路永不因精排故障中断。

- local：fastembed ONNX（bge-reranker-v2-m3-int8，懒加载 ~1-2 分钟，24ms/条）
- api：硅基流动 /rerank（免费档，fp16 原版模型，免本地加载）
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 硅基流动 /rerank 单请求文档数上限；超出分片，按 relevance_score 合并
# （v2-m3 输出 sigmoid 归一分，跨请求可比）
API_MAX_DOCS = 32


class Reranker:
    """懒加载单例（local 后端首次调用拉起 ONNX 会话 ~1-2 分钟）。"""

    _instance: "Reranker | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._http: httpx.Client | None = None  # 持久连接（复用 TLS 会话）

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=settings.rerank_api_base_url,
                headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
                timeout=30,
            )
        return self._http

    @classmethod
    def get(cls) -> "Reranker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def _ensure_local(self):
        if self._model is None and not self._failed:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._model = TextCrossEncoder(settings.rerank_model)
            except Exception as e:  # noqa: BLE001 — 精排缺席不阻塞检索
                self._failed = True
                logger.warning("reranker 本地模型加载失败（本次进程内恒等直出）：%s", e)
        return self._model

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        """对每个 doc 打相关分。后端不可用返回空列表（调用方走原序）。"""
        if not docs:
            return []
        if settings.rerank_backend == "api":
            return self._rerank_api(query, docs)
        model = self._ensure_local()
        if model is None:
            return []
        try:
            return [float(s) for s in model.rerank(query, docs)]
        except Exception:  # noqa: BLE001
            return []

    def _rerank_api(self, query: str, docs: list[str]) -> list[float]:
        """硅基流动 /v1/rerank：分片 + 退避重试；失败分片计 0 分（保序可排序）。"""
        scores: list[float | None] = [None] * len(docs)
        for i in range(0, len(docs), API_MAX_DOCS):
            batch = docs[i:i + API_MAX_DOCS]
            for attempt in range(4):
                try:
                    resp = self._client().post(
                        "/rerank",
                        json={"model": settings.rerank_model,
                              "query": query, "documents": batch},
                    )
                    resp.raise_for_status()
                    for item in resp.json()["results"]:
                        j = i + int(item["index"])
                        if 0 <= j < len(scores):
                            scores[j] = float(item["relevance_score"])
                    break
                except Exception:
                    if attempt == 3:
                        logger.warning("rerank API 分片失败（该批计 0 分）", exc_info=True)
                        break
                    time.sleep(2 ** (attempt + 1))
        return [s if s is not None else 0.0 for s in scores]


reranker = Reranker.get()
