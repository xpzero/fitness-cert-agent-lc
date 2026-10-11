"""混合检索：pgvector dense + pg_trgm sparse → 权威加权 RRF → top_k。

偏差说明（相对设计文档 §5）：
- BM25 → pg_trgm trigram 相似度（pgvector 镜像无 zhparser，中文分词不可用；
  trigram 在 UTF-8 下按字符切分，中文可用），排序语义近似词面相关性。

调用方式：from app.rag.search import searcher，然后 searcher.search(query)。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db import database
from app.llm import llm_client
from app.prompts.retrieval import HYDE_PROMPT
from app.rag.embedder import embedder
from app.rag.fusion import rrf_merge  # 纯函数部分复用

# dense 路：pgvector 余弦距离排序（<=> 越小越近，score=1-distance 归一到 0~1）
DENSE_SQL = sql_text("""
    SELECT c.id, c.page_no, c.section_path, c.content, d.authority_level, d.title,
           1 - (c.embedding <=> :vec) AS score
    FROM chunks c JOIN documents d ON d.id = c.document_id
    ORDER BY c.embedding <=> :vec
    LIMIT :k
""")

# sparse 路：pg_trgm 词面相似度（word_similarity=查询词在文本中的最大相似度），
# 阈值由调用方按分级阶梯传入
SPARSE_SQL = sql_text("""
    SELECT c.id, c.page_no, c.section_path, c.content, d.authority_level, d.title,
           word_similarity(:q, c.content) AS score
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE word_similarity(:q, c.content) > :min_sim
    ORDER BY score DESC
    LIMIT :k
""")


@dataclass
class Candidate:
    chunk_id: str
    page_no: int
    section_path: str
    content: str
    authority_level: int
    title: str = ""             # 所属文档标题（来源卡显示文档名）
    score: float = 0.0
    dense_rank: int | None = None   # M4：分数构成（各通道名次）
    sparse_rank: int | None = None

    @property
    def source_label(self) -> str:
        """来源卡标签："文档名 · P17 §章节路径"（文档名+页码是溯源展示单位）。"""
        sec = f" §{self.section_path}" if self.section_path else ""
        loc = f"P{self.page_no}{sec}" if self.page_no else (sec.strip() or "P?")
        return f"{self.title} · {loc}" if self.title else loc


def _best_rank_merge(primary, secondary):
    """两条 dense 排名合并：每 chunk 取其在两路中的最优名次排序（查询变体集成）。"""
    best: dict = {}
    for rows in (primary, secondary):
        for i, r in enumerate(rows):
            best[r[0]] = min(best.get(r[0], len(rows)), i)
    merged, seen = [], set()
    for r in primary + secondary:
        if r[0] not in seen:
            seen.add(r[0])
            merged.append(r)
    merged.sort(key=lambda r: best[r[0]])
    return merged


class HybridSearcher:
    """混合检索器：dense（原始+HyDE 双路取最优秩）+ sparse → RRF。

    engine 构造期注入（测试/多库场景）或懒取进程级 database.engine。
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = database.engine
        return self._engine

    def _fetch_rows(self, sql, params) -> list[tuple]:
        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).all()
        # 列序：id, page_no, section_path, content, authority_level, title, score
        return [(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6])) for r in rows]

    def _hyde_vector(self, query: str) -> list[float] | None:
        """HyDE：用假设性答案增强查询向量（口语问句 vs 教材文本的语义桥接）。
        LLM 失败时返回 None，调用方回退到原始查询向量。"""
        try:
            hyp = llm_client.chat_fast(
                [{"role": "user", "content": HYDE_PROMPT.format(query=query)}],
                temperature=0.2,
            )
            return embedder.embed_one(f"{query}\n{hyp}") if hyp else None
        except Exception:  # noqa: BLE001
            return None

    def search(self, query: str, *, top_k: int | None = None,
               hyde: bool = True,
               retrieval_mode: str = "hybrid") -> list[Candidate]:
        """dense（原始+HyDE 双路取最优秩）+ sparse → RRF → top_k。

        retrieval_mode（M4 检索试驾）：hybrid 默认 | dense 仅语义 | sparse 仅词面。
        返回的 Candidate 带 dense_rank/sparse_rank（分数构成，供前端展示）。
        """
        top_k = top_k or settings.search_top_k

        dense_rows = self._fetch_rows(DENSE_SQL, {"vec": str(embedder.embed_one(query)),
                                                  "k": settings.dense_top_k})
        if hyde and retrieval_mode != "sparse":
            # HyDE 双路：原始查询向量 + 假设答案向量各检索一次，按最优名次融合
            # （口语问句与教材表述的向量差距由假设答案桥接）
            hyde_vec = self._hyde_vector(query)
            if hyde_vec:
                hyde_rows = self._fetch_rows(DENSE_SQL, {"vec": str(hyde_vec),
                                                         "k": settings.dense_top_k})
                dense_rows = _best_rank_merge(dense_rows, hyde_rows)

        sparse_rows = []
        if retrieval_mode != "dense":
            # 词面阈值分级回退：先用严格阈值，整级空手再逐级放宽——
            # 短口语查询与长文档的 word_similarity 普遍偏低，固定阈值会一无所获
            for min_sim in settings.sparse_min_sim_ladder:
                sparse_rows = self._fetch_rows(SPARSE_SQL, {
                    "q": query, "min_sim": min_sim, "k": settings.sparse_top_k,
                })
                if sparse_rows:
                    break
        if retrieval_mode == "sparse":
            dense_rows = []

        # 各通道名次表（供 Candidate 分数构成展示）；authority_by_id 供 RRF 加权
        dense_rank = {r[0]: i for i, r in enumerate(dense_rows, 1)}
        sparse_rank = {r[0]: i for i, r in enumerate(sparse_rows, 1)}
        authority_by_id = {r[0]: r[4] for r in dense_rows + sparse_rows}
        merged = rrf_merge(
            [r[0] for r in dense_rows],
            [r[0] for r in sparse_rows],
            top_k=top_k,
            authority=authority_by_id,
        )
        score_map = dict(merged)
        rows_by_chunk_id = {r[0]: r for r in dense_rows + sparse_rows}

        candidates = [
            Candidate(chunk_id=cid, page_no=rows_by_chunk_id[cid][1],
                      section_path=rows_by_chunk_id[cid][2],
                      content=rows_by_chunk_id[cid][3],
                      authority_level=rows_by_chunk_id[cid][4],
                      title=rows_by_chunk_id[cid][5],
                      score=score_map[cid],
                      dense_rank=dense_rank.get(cid), sparse_rank=sparse_rank.get(cid))
            for cid, _ in merged if cid in rows_by_chunk_id
        ]
        return candidates


searcher = HybridSearcher()  # 进程级单例（engine 懒取）
