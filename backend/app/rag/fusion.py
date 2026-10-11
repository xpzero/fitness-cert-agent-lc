"""检索融合（纯函数部分）：RRF 融合 + 权威级加权。

真检索（pgvector dense / pg_trgm sparse）在 search.py——
本模块只放可独立单测的融合算法。
"""
from __future__ import annotations

from app.config import settings


def rrf_merge(
    dense: list[str],
    sparse: list[str],
    *,
    top_k: int | None = None,
    authority: dict[str, int] | None = None,
    k: int | None = None,
    channel_weights: tuple = (0.65, 0.35),
) -> list[tuple[str, float]]:
    """加权 Reciprocal Rank Fusion：
    score = Σ channel_weight * authority_weight / (k + rank)

    dense/sparse 为按序的 chunk_id 列表（rank 从 1 开始）；
    channel_weights 对位 (dense, sparse) 两通道的权重（dense 主导，sparse 补词面）；
    authority: chunk_id → 权威级(1/2/3)，用 settings.authority_weights 做微调。
    返回 [(chunk_id, score)] 按 score 降序。
    """
    k = k or settings.rrf_k
    weights = settings.authority_weights
    authority = authority or {}
    scores: dict[str, float] = {}
    for channel_weight, ranking in zip(channel_weights, (dense, sparse)):
        for rank, cid in enumerate(ranking, start=1):
            lvl = authority.get(cid, 1)
            w = weights[lvl - 1] if 1 <= lvl <= len(weights) else 1.0
            scores[cid] = scores.get(cid, 0.0) + channel_weight * w / (k + rank)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_k] if top_k else ranked
