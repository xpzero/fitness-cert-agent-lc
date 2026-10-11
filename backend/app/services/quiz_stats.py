"""刷题侧统计：考点覆盖分析、题库徽章计数。

调用方式：from app.services.quiz_stats import stats，然后 stats.coverage_summary(...)。
"""
from __future__ import annotations

from datetime import date

from app.services.repositories import repo


class QuizStats:
    """刷题页统计（依赖进程级 repo 单例）。"""

    def coverage_summary(self, cert_id: str) -> dict:
        """考点覆盖分析：每考点已验证题数，未覆盖考点单列。"""
        rows = repo.exam_point_counts(cert_id)
        chapters: dict[str, dict] = {}
        for row in rows:
            ch = chapters.setdefault(row["chapter"], {"chapter": row["chapter"],
                                                      "covered": 0, "total": 0,
                                                      "points": []})
            ch["total"] += 1
            ch["covered"] += 1 if row["n"] else 0
            ch["points"].append({"id": row["id"], "title": row["title"],
                                 "questions": row["n"]})
        uncovered = [p["id"] for ch in chapters.values() for p in ch["points"]
                     if not p["questions"]]
        return {"cert_id": cert_id, "chapters": list(chapters.values()),
                "covered_total": len(rows) - len(uncovered), "uncovered": uncovered}

    def badge_counts(self, user_id: str, today: date | None = None) -> dict:
        """刷题页徽章：到期错题/错题总数/收藏数。"""
        due, total = repo.wrongbook_counts(user_id, today or date.today())
        return {"wrong": due, "wrong_total": total,
                "favorites": repo.favorite_count(user_id)}


stats = QuizStats()  # 进程级单例
