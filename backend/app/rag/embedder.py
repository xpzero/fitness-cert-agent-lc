"""Embedding 后端：fastembed ONNX 本地推理（免 API key）。

当前基线 intfloat/multilingual-e5-large（1024 维多语言，中英互检；EMBED_MODEL/EMBED_DIM
改 env 可换）。e5 系列要求输入带 "query:"/"passage:" 前缀——由本模块按模型自动添加，
调用方无感。模型懒加载（cached_property）——import 本模块不触发模型下载。
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
