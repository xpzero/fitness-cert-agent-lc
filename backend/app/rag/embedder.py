"""Embedding 后端：fastembed ONNX 本地推理（免 API key）。

基线 BAAI/bge-small-zh-v1.5（512 维，EMBED_DIM 驱动，换模型改 env 即可）。
模型懒加载（cached_property）——import 本模块不触发模型下载。

历史：原方案 BGE-M3(1024d) 本地跑需 torch/2.3GB 下载且 fastembed 0.8 不支持；
zhipu API 后端因 coding-plan key 无 embedding 配额已移除（2026-10-10）。
"""
from __future__ import annotations

from functools import cached_property

from langchain_core.embeddings import Embeddings

from app.config import settings


class Embedder:
    """本地 ONNX 向量化（批量）。"""

    @cached_property
    def _local(self):
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=settings.embed_model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。"""
        if not texts:
            return []
        return [list(map(float, v)) for v in self._local.embed(texts)]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


embedder = Embedder()  # 进程级单例（local 模型懒加载）


class LangChainEmbeddings(Embeddings):
    """langchain Embeddings 接口适配器：让 embedder 能以标准身份参与
    向量库/检索器组装（不引 langchain-community）。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embedder.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return embedder.embed_one(text)
