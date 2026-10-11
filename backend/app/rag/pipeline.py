"""文档解析与入库管线（M1/M2 共享）：文件 → 带页码 markdown → chunks → embedding → pgvector。

被三处复用：scripts/ingest.py（种子语料）、kb_worker（上传解析）、API 重解析。
进度通过 progress_cb(phase, percent, detail) 上报给 ingest_jobs。

调用方式：from app.rag.pipeline import ingest，然后 ingest.ingest_markdown(...)。
extract_text / doc_id_from_title 是无状态纯工具，保留模块级。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import text as sql_text

from app.config import settings
from app.db import database
from app.llm import llm_client
from app.models.tables import Chunk as ChunkRow, Document
from app.prompts.retrieval import TRANSLATE_PROMPT
from app.rag.chunking import make_chunks
from app.rag.embedder import embedder

SUPPORTED_EXT = {".md", ".txt", ".pdf"}

# 盗版扫描件常见"文字层只有水印广告"的页：关键词命中且总长 <150 字符即判定
# （正文页通常数百字符，不会误伤；这类页若不 OCR，广告文本会顶替正文进索引）
WATERMARK_AD_RE = re.compile(r"加微信|加微[:：]|极速PDF|买书|免费获得|更多资源|更多优惠|代找")


def doc_id_from_title(title: str) -> str:
    return "doc-" + hashlib.md5(title.encode()).hexdigest()[:10]


def extract_text(path: Path, progress_cb=None) -> tuple[str, bool, list[int]]:
    """文件 → 带页码标记的 markdown。返回 (text, used_ocr, ocr_failed_pages)。

    .md/.txt 直接读；PDF 逐页混合提取：有文字层直接用，空白页（扫描/字体损坏）
    与纯水印页（文字层只剩盗版广告）单页转 Vision OCR——三类页混排的 PDF 不再
    整本误判。OCR 失败的页号记入第三返回值（单页失败不拖垮整本，但调用方应把
    缺失页警示给用户）。
    """
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return path.read_text(encoding="utf-8", errors="ignore"), False, []

    import pymupdf

    from scripts.ocr_pdf import RENDER_SCALE, ocr_image, reset_orientation

    reset_orientation()  # 方向缓存按文档隔离：worker 常驻线程会连续解析多份 PDF
    pdf_doc = pymupdf.open(path)
    page_parts: list[str] = []
    used_ocr = False
    failed_pages: list[int] = []
    page_count = len(pdf_doc)
    for i in range(page_count):
        page = pdf_doc[i]
        text = page.get_text().strip()
        # 空白页/字体损坏页/纯水印页 → 渲染 + OCR
        if len(text) < 30 or (len(text) < 150 and WATERMARK_AD_RE.search(text)):
            try:
                # pymupdf 单页渲染：Quartz/PDFKit 的 thumbnail 链路每页驻留
                # ~10-30MB（autorelease pool 亦回收不净），曾致整本扫描件吃满 80GB
                pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE))
                text = ocr_image(pix.tobytes("png"))
                used_ocr = True
            except Exception:  # noqa: BLE001 — 单页失败不拖垮整本，但记页号供警示
                text = ""
                failed_pages.append(i + 1)
        # [[P页码]] 标记是后续引用溯源的根基（讲题/QA 出处都靠它定位）
        page_parts.append(f"\n[[P{i+1}]]\n{text}")
        if progress_cb and (i + 1) % 10 == 0:
            progress_cb("extract", int((i + 1) / page_count * 100),
                        f"提取 {i+1}/{page_count} 页"
                        + ("（含 OCR）" if used_ocr else ""))
    pdf_doc.close()
    return "".join(page_parts), used_ocr, failed_pages


class IngestPipeline:
    """markdown → chunks →（跨语言摘要前置）→ embedding → 落库。

    四个阶段各一个方法（ingest_markdown 编排），进度回调贯穿全链路。
    """

    def ingest_markdown(self, doc_id: str, title: str, markdown_text: str, *,
                        authority_level: int,
                        source_type: str, filename: str = "",
                        progress_cb=None, replace_existing: bool = True) -> int:
        """markdown → chunks → embedding → 落库。返回 chunk 数
        （幂等：replace_existing 时先清旧）。"""
        database.init_db()
        chunks = make_chunks(markdown_text, cert_id=settings.default_cert,
                             source_type=source_type,
                             authority_level=authority_level,
                             max_chars=settings.chunk_max_chars,
                             overlap=settings.chunk_overlap_chars)
        if not chunks:
            raise ValueError("解析结果为空（无有效内容）")
        self._prepend_zh_summary(chunks, progress_cb)
        vectors = self._embed_chunks(chunks, progress_cb)
        self._persist(doc_id, title, chunks, vectors,
                      authority_level=authority_level, source_type=source_type,
                      filename=filename, replace_existing=replace_existing)
        if progress_cb:
            progress_cb("done", 100, f"{len(chunks)} chunks 已索引")
        return len(chunks)

    def _prepend_zh_summary(self, chunks, progress_cb) -> None:
        """跨语言增强：英文为主的 chunk 生成中文摘要前置——中文查询也能命中英文教材。"""
        en_chunks = [c for c in chunks
                     if sum(ch.isascii() and ch.isalpha() for ch in c.content)
                     / max(1, sum(not ch.isspace() for ch in c.content)) > 0.5]
        if not en_chunks:
            return
        translated_count = 0
        for c in en_chunks:
            try:
                summary_text = llm_client.chat_fast([
                    {"role": "user",
                     "content": TRANSLATE_PROMPT.format(content=c.content[:500])},
                ], temperature=0.2)
                c.content = f"【中文摘要】{summary_text.strip()}\n【原文】{c.content}"
            except Exception:  # noqa: BLE001 — 翻译失败保留原文
                pass
            translated_count += 1
            if progress_cb and translated_count % 20 == 0:
                progress_cb("embed", 2,
                            f"英文摘要 {translated_count}/{len(en_chunks)}")

    def _embed_chunks(self, chunks, progress_cb) -> list[list[float]]:
        if progress_cb:
            progress_cb("embed", 5, f"共 {len(chunks)} 块")

        vectors: list[list[float]] = []
        batch_size = max(1, settings.embed_batch_size * 4)   # 上传场景批大一点
        for i in range(0, len(chunks), batch_size):
            vectors.extend(embedder.embed(
                [c.content for c in chunks[i:i + batch_size]]))
            if progress_cb:
                progress_cb("embed", int((len(vectors) / len(chunks)) * 90) + 5,
                            f"向量化 {len(vectors)}/{len(chunks)}")
        return vectors

    def _persist(self, doc_id: str, title: str, chunks, vectors, *,
                 authority_level: int, source_type: str, filename: str,
                 replace_existing: bool) -> None:
        with database.engine.begin() as conn:
            # 同一事务内先删旧后插新：重复摄取同一 doc_id 时保持幂等替换，
            # 中途失败整体回滚，不会出现"新旧 chunks 并存"的中间态
            if replace_existing:
                conn.execute(sql_text("DELETE FROM chunks WHERE document_id = :d"),
                             {"d": doc_id})
            conn.execute(sql_text("DELETE FROM documents WHERE id = :d"), {"d": doc_id})
            conn.execute(Document.__table__.insert().values(
                id=doc_id, title=title, source_type=source_type,
                cert_ids=[settings.default_cert], authority_level=authority_level,
                status="indexed", filename=filename,
            ))
            conn.execute(ChunkRow.__table__.insert(), [
                dict(id=f"{doc_id}-{c.chunk_index}", document_id=doc_id,
                     chunk_index=c.chunk_index, page_no=c.page_no,
                     section_path=c.section_path[:250], content=c.content,
                     exam_point_ids=[], embedding=v)
                for c, v in zip(chunks, vectors)
            ])


ingest = IngestPipeline()  # 进程级单例


def count_referencing_questions(doc_id: str) -> int:
    """删除保护：引用该文档 chunk 的已验证题数（source_chunk_ids 前缀匹配）。"""
    with database.engine.connect() as conn:
        return conn.execute(sql_text("""
            SELECT count(*) FROM questions
            WHERE verified AND EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(source_chunk_ids) AS cid
                WHERE cid LIKE :prefix)
        """), {"prefix": f"{doc_id}-%"}).scalar()
