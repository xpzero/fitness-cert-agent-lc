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
    """本地 ONNX 向量化（批量）。e5 类模型自动加 query/passage 前缀。"""

    @cached_property
    def _local(self):
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=settings.embed_model)

    @cached_property
    def _needs_prefix(self) -> bool:
        return "e5" in settings.embed_model.lower()

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """查询侧向量化（e5 加 query: 前缀）。"""
        if self._needs_prefix:
            texts = [f"query: {t}" for t in texts]
        return self.embed(texts)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """文档侧向量化（e5 加 passage: 前缀；摄取/重嵌入用）。"""
        if self._needs_prefix:
            texts = [f"passage: {t}" for t in texts]
        return self.embed(texts)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化（无前缀原样）。"""
        if not texts:
            return []
        return [list(map(float, v)) for v in self._local.embed(texts)]

    def embed_one(self, text: str) -> list[float]:
        return self.embed_queries([text])[0]


embedder = Embedder()  # 进程级单例（local 模型懒加载）


class LangChainEmbeddings(Embeddings):
    """langchain Embeddings 接口适配器：让 embedder 能以标准身份参与
    向量库/检索器组装（不引 langchain-community）。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embedder.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return embedder.embed_one(text)
