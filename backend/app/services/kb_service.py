"""知识库业务逻辑（从 API 端点下沉）：上传/删除规则、文档列表、评测编排、报告解析。

调用方式：from app.services.kb_service import kb，然后 kb.upload_documents(...)。
依赖（database / ingest_worker / searcher / llm_client）均为进程级单例。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import text as sql_text

from app.config import PROJECT_ROOT, settings
from app.db import database
from app.kb_worker import ingest_worker
from app.llm import llm_client
from app.prompts.eval import EVAL_QUESTION_PROMPT
from app.rag.pipeline import (SUPPORTED_EXT, count_referencing_questions,
                              doc_id_from_title)
from app.rag.search import searcher

EVAL_REPORT_PATH = PROJECT_ROOT / "eval" / "report" / "latest-retrieval.md"
# 单文档评测：近义等价 chunk 并入相关集的 embedding 相似度下限
EVAL_EQUIV_SIMILARITY = 0.80
EVAL_MIN_CHUNK_LEN = 150
EVAL_MIN_SAMPLES = 3
EVAL_MAX_SAMPLES = 12


def latest_lib_recall_display() -> str:
    """从最近一次检索评测报告提取库级 Recall@5（展示用，缺失返回 —）。"""
    if not EVAL_REPORT_PATH.exists():
        return "—"
    m = re.search(r"Recall@5 \| (0\.\d+)", EVAL_REPORT_PATH.read_text())
    return m.group(1) if m else "—"


class KbService:
    """知识库业务逻辑：上传/删除规则、文档列表、重解析、单文档召回评测。"""

    async def upload_documents(self, files: list[UploadFile],
                               authority: int) -> list[dict]:
        """校验扩展名 → 落盘 → documents 表登记（queued）→ 入解析队列。"""
        results = []
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext not in SUPPORTED_EXT:
                results.append({"filename": f.filename, "ok": False,
                                "reason": f"不支持的格式 {ext}（支持 md/txt/pdf）"})
                continue
            title = Path(f.filename).stem
            doc_id = doc_id_from_title(title + ext)
            # 落盘名用 doc_id（同名不同路径的文件互不覆盖）；filename 列存
            # 原始上传名——它是展示与引用溯源字段，worker 按 doc_id.* 找文件
            original_name = Path(f.filename).name
            dest = settings.uploads_dir / f"{doc_id}{ext}"
            with dest.open("wb") as out:
                out.write(await f.read())
            with database.engine.begin() as conn:
                conn.execute(sql_text("""
                    INSERT INTO documents (id, title, source_type, cert_ids, authority_level,
                                           status, filename, file_size)
                    VALUES (:id, :t, '上传', CAST(:certs AS jsonb), :a, 'queued', :f, :sz)
                    ON CONFLICT (id) DO UPDATE SET status = 'queued', filename = :f,
                                                   file_size = :sz
                """), {"id": doc_id, "t": title, "a": max(1, min(3, authority)),
                       "certs": json.dumps([settings.default_cert]), "f": original_name,
                       "sz": f.size})
            ingest_worker.enqueue(doc_id)
            results.append({"filename": f.filename, "ok": True,
                            "document_id": doc_id, "status": "queued"})
        return results

    def documents_overview(self, page: int = 1, page_size: int = 10,
                           q: str = "", authority: int = 0, status: str = "") -> dict:
        """文档列表（按标题排序分页，含状态与最新任务进度，供前端 3s 轮询）。

        q 按标题/文件名 ILIKE 过滤；authority>0 按权威级；status 按文档状态。
        同时返回库级汇总（总数/已索引/chunks/解析中）。
        """
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        like = f"%{q.strip()}%" if q.strip() else None
        with database.engine.connect() as conn:
            rows = conn.execute(sql_text("""
                SELECT * FROM (
                    SELECT d.id, d.title, d.authority_level, d.status, d.filename, d.error, d.file_size,
                           d.created_at, d.updated_at,
                           count(c.id) AS chunks,
                           COALESCE(min(NULLIF(c.page_no, 0)), 0) AS min_page,
                           max(c.page_no) AS max_page
                    FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                    WHERE (CAST(:like AS text) IS NULL OR d.title ILIKE :like
                           OR d.filename ILIKE :like)
                    AND (:auth = 0 OR d.authority_level = :auth)
                    AND (CAST(:st AS text) = '' OR d.status = :st)
                    GROUP BY d.id ORDER BY d.title
                ) t
                LIMIT :limit OFFSET :offset
            """), {"limit": page_size, "offset": (page - 1) * page_size,
                   "like": like, "auth": authority, "st": status}).mappings().all()
            filtered_total = conn.execute(sql_text("""
                SELECT count(*) FROM documents
                WHERE (CAST(:like AS text) IS NULL OR title ILIKE :like OR filename ILIKE :like)
                  AND (:auth = 0 OR authority_level = :auth)
                  AND (CAST(:st AS text) = '' OR status = :st)
            """), {"like": like, "auth": authority, "st": status}).scalar()
            total, indexed, active = conn.execute(sql_text("""
                SELECT count(*),
                       count(*) FILTER (WHERE status = 'indexed'),
                       count(*) FILTER (WHERE status IN ('queued', 'parsing', 'embedding'))
                FROM documents
            """)).one()
            total_chunks = conn.execute(sql_text("SELECT count(*) FROM chunks")).scalar()
        docs = []
        for r in rows:
            d = dict(r)
            # 仅解析/向量化中展示实时进度；queued 不挂旧任务（避免显示上次的失败信息）
            if d["status"] in ("parsing", "embedding"):
                d["job"] = ingest_worker.get_latest_job(d["id"])
            docs.append(d)
        return {"documents": docs,
                "lib_recall": latest_lib_recall_display(),
                "total": filtered_total, "library_total": total,
                "indexed": indexed, "total_chunks": total_chunks,
                "active": active, "page": page, "page_size": page_size}

    def delete_document(self, doc_id: str, force_delete: bool = False) -> dict:
        """删除文档（级联 chunks）。删除保护：有已验证题引用时需 force_delete=true
        （同时把这些题下架 verified=false，避免题库悬空）。"""
        refs = count_referencing_questions(doc_id)
        unverified_question_count = 0
        if refs and not force_delete:
            return {"ok": False, "refs": refs,
                    "reason": f"有 {refs} 道已验证题引用此文档；force=true 可强制删除（题目将下架）"}
        with database.engine.begin() as conn:
            if refs:
                conn.execute(sql_text("""
                    UPDATE questions SET verified = false WHERE verified AND EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(source_chunk_ids) AS cid
                        WHERE cid LIKE :prefix)
                """), {"prefix": f"{doc_id}-%"})
                unverified_question_count = refs
            conn.execute(sql_text("DELETE FROM chunks WHERE document_id = :d"),
                         {"d": doc_id})
            deleted_count = conn.execute(
                sql_text("DELETE FROM documents WHERE id = :d"), {"d": doc_id}).rowcount
            conn.execute(sql_text("DELETE FROM ingest_jobs WHERE document_id = :d"),
                         {"d": doc_id})
        # 清理落盘文件
        for f in settings.uploads_dir.glob(f"{doc_id}.*"):
            f.unlink(missing_ok=True)
        return {"ok": bool(deleted_count), "refs_dropped": unverified_question_count}

    def reingest_document(self, doc_id: str) -> dict:
        """重新解析（failed 后重试 / 换权威级后重建索引）。"""
        with database.engine.connect() as conn:
            row = conn.execute(sql_text("SELECT filename FROM documents WHERE id = :d"),
                               {"d": doc_id}).first()
        if not row or not row[0]:
            return {"ok": False, "reason": "文档不存在或非上传文档（种子语料用 make ingest）"}
        with database.engine.begin() as conn:
            conn.execute(sql_text("UPDATE documents SET status='queued', error='' WHERE id = :d"),
                         {"d": doc_id})
        ingest_worker.enqueue(doc_id)
        return {"ok": True, "status": "queued"}

    # ------------------------------------------------- 单文档召回评测

    def run_document_retrieval_eval(self, doc_id: str, n_samples: int = 8) -> dict:
        """单文档召回评测（M3）：采样 chunk → LLM 生成考生问题 → 混合检索
        → Recall@5 / MRR@5 + miss 清单（近义等价 chunk 按 embedding 相似度并入相关集）。"""
        import numpy as np

        min_samples, max_samples = EVAL_MIN_SAMPLES, EVAL_MAX_SAMPLES
        engine = database.engine
        with engine.connect() as conn:
            chunks = conn.execute(sql_text("""
                SELECT id, content, embedding::text FROM chunks
                WHERE document_id = :d AND length(content) >= :min_len ORDER BY random() LIMIT :n
            """), {"d": doc_id, "min_len": EVAL_MIN_CHUNK_LEN,
                   "n": max(min_samples, min(max_samples, n_samples))}).all()
        if len(chunks) < 3:
            return {"ok": False, "reason": "可采样 chunk 不足（需 ≥3 个长度 ≥150 的块）"}

        sampled_chunk_vectors = {c[0]: np.array(json.loads(c[2])) for c in chunks}
        eval_cases, skipped_count = [], 0
        for cid, content, _ in chunks:
            try:
                question = llm_client.chat_json([
                    {"role": "system", "content": EVAL_QUESTION_PROMPT},
                    {"role": "user", "content": content[:800]},
                ], model_tier="gen", temperature=0.5).get("question", "").strip()
                if question:
                    eval_cases.append({"query": question, "relevant": cid})
            except Exception:  # noqa: BLE001
                skipped_count += 1
        if len(eval_cases) < 3:
            return {"ok": False, "reason": f"题目生成失败过多（{skipped_count} skipped）"}

        all_chunk_vectors = {}
        with engine.connect() as conn:
            for r in conn.execute(sql_text("SELECT id, embedding::text FROM chunks")).all():
                all_chunk_vectors[r[0]] = np.array(json.loads(r[1]))

        def expand_relevant_set(cid: str) -> set:
            """相关集扩展：与采样 chunk 向量余弦 ≥0.80 的近义等价 chunk 一并视为
            相关（同一知识点被切到相邻块时，命中任一块都算召回）。"""
            source_vector, equivalent_ids = sampled_chunk_vectors[cid], {cid}
            for other, v in all_chunk_vectors.items():
                if other != cid:
                    den = np.linalg.norm(source_vector) * np.linalg.norm(v) + 1e-9
                    if float(np.dot(source_vector, v) / den) >= EVAL_EQUIV_SIMILARITY:
                        equivalent_ids.add(other)
            return equivalent_ids

        hits_at_5 = mrr_sum = 0
        miss_details = []
        for case in eval_cases:
            candidates = searcher.search(case["query"])
            top5_chunk_ids = [c.chunk_id for c in candidates[:5]]
            relevant_chunk_ids = expand_relevant_set(case["relevant"])
            rank = next((r for r, cid in enumerate(top5_chunk_ids, 1)
                         if cid in relevant_chunk_ids), None)
            if rank:
                hits_at_5 += 1
                mrr_sum += 1 / rank
            else:
                miss_details.append({"query": case["query"], "expected": case["relevant"],
                                     "got_top3": [f"{c.source_label}"
                                                  for c in candidates[:3]]})
        case_count = len(eval_cases)
        return {"ok": True, "samples": case_count, "skipped": skipped_count,
                "recall5": round(hits_at_5 / case_count, 3),
                "mrr5": round(mrr_sum / case_count, 3),
                "misses": miss_details}


kb = KbService()  # 进程级单例
