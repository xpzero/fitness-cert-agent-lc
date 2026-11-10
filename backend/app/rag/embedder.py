"""Embedding 后端：本地 fastembed ONNX 或 OpenAI 兼容 API（EMBED_BACKEND 切换）。

- local：fastembed ONNX 免 key（bge-small-zh 基线。BGE-M3 本地跑需 torch/2.3GB
  下载且 fastembed 0.8 不支持——m3 走 api 后端）
- api：OpenAI 兼容 /embeddings（硅基流动免费 BAAI/bge-m3，1024 维多语言，
  中英互检；reranker 同族 bge-reranker-v2-m3 语义空间一致）

e5 系列要求输入带 "query:"/"passage:" 前缀——由本模块按模型名自动添加，
调用方无感。模型/客户端懒加载（cached_property）——import 本模块不触发
模型下载或网络连接。
"""
from __future__ import annotations

from functools import cached_property

from langchain_core.embeddings import Embeddings

from app.config import settings

# 硅基流动 /embeddings 单请求条数上限（bge-m3；本地批量另受 EMBED_BATCH_SIZE 约束）
API_MAX_BATCH = 32


class Embedder:
    """向量化（批量）：按 settings.embed_backend 路由本地 ONNX 或 API。"""

    @cached_property
    def _local(self):
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=settings.embed_model)

    @cached_property
    def _api(self):
        from openai import OpenAI

        if not settings.embed_api_key:
            raise ValueError("EMBED_BACKEND=api 需要在 .env 配置 EMBED_API_KEY")
        return OpenAI(base_url=settings.embed_api_base_url,
                      api_key=settings.embed_api_key,
                      max_retries=3)  # 429/5xx 传输层自动退避重试

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
        if settings.embed_backend == "api":
            return self._embed_via_api(texts)
        return [list(map(float, v)) for v in self._local.embed(texts)]

    def _embed_via_api(self, texts: list[str]) -> list[list[float]]:
        """OpenAI 兼容 /embeddings：按 API_MAX_BATCH 分片，结果保持输入顺序。
        网络抖动（SSL EOF 等，SDK 内置重试之外）整批退避重试：2/4/8s 共 4 次。"""
        import time

        out: list[list[float]] = []
        for i in range(0, len(texts), API_MAX_BATCH):
            batch = texts[i:i + API_MAX_BATCH]
            for attempt in range(4):
                try:
                    resp = self._api.embeddings.create(
                        model=settings.embed_model, input=batch)
                    out.extend(d.embedding for d in resp.data)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** (attempt + 1))
        return out

    def embed_one(self, text: str) -> list[float]:
        return self.embed_queries([text])[0]


embedder = Embedder()  # 进程级单例（local 模型/ api 客户端懒加载）


class LangChainEmbeddings(Embeddings):
    """langchain Embeddings 接口适配器：让 embedder 能以标准身份参与
    向量库/检索器组装（不引 langchain-community）。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embedder.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return embedder.embed_one(text)
