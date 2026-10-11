"""跨模块共享的查询（薄仓储）——API 聚合端点与子图节点共用以消除重复 SQL。

只收编有 ≥2 处使用（或即将被子图复用）的查询；单端点私有的 SQL 留在原处。
Repository 构造期注入 engine（缺省懒取 database.engine），
方法不再逐个传 engine 参数。
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from app.db import database


class CoverageTotals(NamedTuple):
    covered_count: int
    total_count: int


class WrongbookCounts(NamedTuple):
    due_count: int
    total_count: int


class ChunkRef(NamedTuple):
    """chunk 的溯源引用（页码 + 正文 + 所属文档名），chunks_by_ids 的值类型。"""
    page_no: int
    content: str
    title: str = ""   # 所属文档标题（讲题/教练材料标签用它，避免 chunk 哈希 id 泄进讲解）


# 每考点已验证题数：/coverage、/plan/overview 覆盖率共用（quizgen 选题随后接入）
EXAM_POINT_COUNTS_SQL = sql_text("""
    SELECT ep.chapter, ep.id, ep.title, count(q.id) AS n
    FROM exam_points ep
    LEFT JOIN questions q ON q.exam_point_ids ? ep.id AND q.verified
    WHERE ep.cert_id = :c AND ep.parent_id <> ''
    GROUP BY ep.chapter, ep.id, ep.title ORDER BY ep.chapter, ep.id
""")

ACTIVE_PLAN_SQL = sql_text(
    "SELECT id, cert_id, exam_date, plan::text AS plan_text, status FROM study_plans "
    "WHERE user_id = :u AND status='active' ORDER BY exam_date DESC LIMIT 1")


class Repository:
    """共享查询仓储：engine 注入或懒取进程单例，方法只关心业务参数。"""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = database.engine
        return self._engine

    def active_plan_row(self, user_id: str):
        with self.engine.connect() as conn:
            return conn.execute(ACTIVE_PLAN_SQL, {"u": user_id}).mappings().first()

    def exam_point_counts(self, cert_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(EXAM_POINT_COUNTS_SQL,
                                                  {"c": cert_id}).mappings().all()]

    def coverage_totals(self, cert_id: str) -> CoverageTotals:
        """(已覆盖考点数, 考点总数)。"""
        counts = self.exam_point_counts(cert_id)
        covered = sum(1 for r in counts if r["n"])
        return CoverageTotals(covered, len(counts))

    def answered_count(self, user_id: str) -> int:
        with self.engine.connect() as conn:
            return conn.execute(sql_text("SELECT count(*) FROM user_answers WHERE user_id = :u"),
                                {"u": user_id}).scalar()

    def recent_mock_scores(self, user_id: str, limit: int = 3) -> list[float]:
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(sql_text(
                "SELECT score FROM mock_reports WHERE user_id = :u "
                "ORDER BY created_at DESC LIMIT :n"), {"u": user_id, "n": limit}).all()]

    def answer_days(self, user_id: str, limit: int = 30) -> list[date]:
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(sql_text(
                "SELECT DISTINCT created_at::date FROM user_answers WHERE user_id = :u "
                "ORDER BY 1 DESC LIMIT :n"), {"u": user_id, "n": limit}).all()]

    def checkins_on_day(self, user_id: str, today: date) -> dict[int, bool]:
        with self.engine.connect() as conn:
            return {r[0]: r[1] for r in conn.execute(sql_text(
                "SELECT task_no, done FROM study_checkins WHERE user_id = :u AND day = :d"),
                {"u": user_id, "d": today}).all()}

    def wrongbook_counts(self, user_id: str, today: date) -> WrongbookCounts:
        """(到期错题数, 错题总数)。"""
        with self.engine.connect() as conn:
            due = conn.execute(sql_text(
                "SELECT count(*) FROM wrong_book WHERE user_id = :u AND due_date <= :t"),
                {"u": user_id, "t": today}).scalar()
            total = conn.execute(sql_text(
                "SELECT count(*) FROM wrong_book WHERE user_id = :u"),
                {"u": user_id}).scalar()
        return WrongbookCounts(due, total)

    def favorite_count(self, user_id: str) -> int:
        with self.engine.connect() as conn:
            return conn.execute(sql_text("SELECT count(*) FROM favorites WHERE user_id = :u"),
                                {"u": user_id}).scalar()

    def document_chunks(self, doc_id: str, limit: int = 40) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT id, page_no, section_path, content FROM chunks
                WHERE document_id = :d ORDER BY chunk_index LIMIT :n
            """), {"d": doc_id, "n": limit}).mappings().all()
        return [dict(r) for r in rows]

    def chunks_by_ids(self, chunk_ids: list[str]) -> dict[str, ChunkRef]:
        """按 id 批量取 chunk（消除逐题逐 chunk 建连接的 N+1）。

        返回 {chunk_id: ChunkRef(page_no, content, title)}；查不到的 id 不在结果中。
        """
        if not chunk_ids:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT c.id, c.page_no, c.content::text, d.title
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = ANY(:ids)
            """), {"ids": sorted(set(chunk_ids))}).all()
        return {r[0]: ChunkRef(r[1], r[2], r[3]) for r in rows}


repo = Repository()  # 进程级单例（engine 懒取）
