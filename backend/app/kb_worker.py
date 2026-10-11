"""知识库后台解析 worker（M2）：单队列单线程，进程内常驻（KbIngestWorker）。

一次只跑一个解析任务（embedding/OCR 抢占本地资源），进度写入 ingest_jobs，
documents.status 同步流转。状态机单一来源见 PHASE_STATUS：
queued → parsing(ocr/extract) → embedding → indexed | failed
队列本身不持久化：进程重启后由 lifespan 调 recover() 按 documents.status 恢复。
"""
from __future__ import annotations

import queue
import threading
import uuid

from sqlalchemy import text as sql_text

from app.config import settings
from app.db import database

# job phase → documents.status（唯一映射表；upload 阶段从未发出，不设条目）
PHASE_STATUS = {"done": "indexed", "failed": "failed",
                "ocr": "parsing", "extract": "parsing", "embed": "embedding"}


class KbIngestWorker:
    """拥有队列、工作线程与恢复逻辑的解析 worker。"""

    def __init__(self) -> None:
        self._queue: "queue.Queue[str]" = queue.Queue()  # document_id
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- 队列

    def enqueue(self, document_id: str) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name="kb-ingest-worker")
                self._thread.start()
        self._queue.put(document_id)

    def requeue_interrupted_documents(self) -> int:
        """启动恢复：把中断状态（queued/parsing/embedding）的文档重新入队。"""
        with database.engine.connect() as conn:
            stuck_rows = conn.execute(sql_text(
                "SELECT id FROM documents WHERE status IN ('queued','parsing','embedding')"
            )).all()
        for (doc_id,) in stuck_rows:
            self.enqueue(doc_id)
        return len(stuck_rows)

    def _loop(self) -> None:
        database.init_db()
        while True:
            doc_id = self._queue.get()
            try:
                self._process_document(doc_id)
            except Exception as e:  # noqa: BLE001 — 兜底：单任务崩溃不能杀死常驻线程
                self._write_progress(doc_id, "failed", 0, f"worker 内部错误: {e}")
            finally:
                self._queue.task_done()

    # ---------------------------------------------------------------- 处理

    def _process_document(self, document_id: str) -> None:
        from pathlib import Path

        from app.rag.pipeline import extract_text, ingest

        engine = database.engine
        with engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT filename, title, authority_level FROM documents WHERE id = :d"),
                {"d": document_id}).first()
        if not row:
            return
        job_id = "job-" + uuid.uuid4().hex[:12]
        # 落盘名是 {doc_id}{ext}（filename 列存的是原始上传名，仅作展示）
        path = next(settings.uploads_dir.glob(f"{document_id}.*"), None)
        if path is None:
            self._write_progress(document_id, "failed", 0,
                                 f"上传文件缺失：uploads/ 下无 {document_id}.*")
            return
        self._write_progress(document_id, "extract", 2, "开始解析", job_id=job_id)
        try:
            markdown_text, used_ocr, ocr_failed = extract_text(
                path, progress_cb=lambda ph, pg, dt:
                self._write_progress(document_id, ph, pg, dt, job_id=job_id))
            chunk_count = ingest.ingest_markdown(
                doc_id=document_id, title=row[1] or path.stem,
                markdown_text=markdown_text,
                authority_level=row[2], source_type="上传", filename=row[0],
                progress_cb=lambda ph, pg, dt: self._write_progress(
                    document_id, ph, pg, dt, job_id=job_id))
            self._write_progress(document_id, "done", 100,
                                 f"{chunk_count} chunks"
                                 f"{'（OCR）' if used_ocr else ''} 已索引",
                                 job_id=job_id)
            if ocr_failed:
                # 部分页 OCR 失败：内容缺失但不判整本失败——页号写 error 列警示
                with engine.begin() as conn:
                    conn.execute(sql_text(
                        "UPDATE documents SET error = :e WHERE id = :d"),
                        {"e": "OCR 未识别页："
                              + ", ".join(f"P{p}" for p in ocr_failed)
                              + "（这些页内容缺失）",
                         "d": document_id})
        except Exception as e:  # noqa: BLE001
            self._write_progress(document_id, "failed", 0, str(e)[:250], job_id=job_id)

    def _write_progress(self, document_id: str, phase: str, progress: int,
                        detail: str, *, job_id: str | None = None) -> None:
        """写进度并同步文档状态；job_id 为空时仅更新文档状态（恢复/兜底路径）。"""
        engine = database.engine
        status = PHASE_STATUS.get(phase, "parsing")
        with engine.begin() as conn:
            if job_id:
                conn.execute(sql_text("""
                    INSERT INTO ingest_jobs (id, document_id, phase, progress, detail, updated_at)
                    VALUES (:id, :doc, :phase, :prog, :detail, now())
                    ON CONFLICT (id) DO UPDATE SET phase = :phase, progress = :prog,
                        detail = :detail, updated_at = now()
                """), {"id": job_id, "doc": document_id, "phase": phase,
                       "prog": progress, "detail": detail[:250]})
            conn.execute(sql_text("UPDATE documents SET status = :s, error = :e WHERE id = :d"),
                         {"s": status, "e": "" if phase != "failed" else detail[:500],
                          "d": document_id})

    # ---------------------------------------------------------------- 查询

    def get_latest_job(self, document_id: str) -> dict | None:
        with database.engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT phase, progress, detail, updated_at FROM ingest_jobs "
                "WHERE document_id = :d ORDER BY updated_at DESC LIMIT 1"),
                {"d": document_id}).first()
        if not row:
            return None
        return {"phase": row[0], "progress": row[1], "detail": row[2],
                "updated_at": str(row[3])}


ingest_worker = KbIngestWorker()  # 进程级单例：API lifespan 与 kb_service 共用
