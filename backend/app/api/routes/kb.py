"""知识库管理端点：上传/列表/删除/重解析/评测/检索试驾/chunk 浏览。"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, UploadFile
from sqlalchemy import text as sql_text

from app.services.kb_service import kb
from app.services.repositories import repo
from app.rag.search import searcher

router = APIRouter()


@router.post("/kb/upload")
async def kb_upload(files: list[UploadFile], authority: int = Form(3)):
    """上传并排队解析（md/txt 直接解析；pdf 自动识别文字层/扫描件）。

    authority: 1 官方 / 2 半官方 / 3 补充（检索 RRF 加权）。
    """
    return {"results": await kb.upload_documents(files, authority)}


@router.get("/kb/documents")
def kb_documents(page: int = 1, page_size: int = 10, q: str = "",
                 authority: int = 0, status: str = "") -> dict:
    """文档列表（分页；q 过滤标题/文件名，authority 权威级，status 状态）。"""
    return kb.documents_overview(page=page, page_size=page_size, q=q,
                                 authority=authority, status=status)


@router.delete("/kb/documents/{doc_id}")
def kb_delete(doc_id: str, force: bool = False) -> dict:
    return kb.delete_document(doc_id, force)


@router.post("/kb/reingest/{doc_id}")
def kb_reingest(doc_id: str) -> dict:
    return kb.reingest_document(doc_id)


@router.post("/kb/documents/{doc_id}/eval")
def kb_eval(doc_id: str, n_samples: int = 8) -> dict:
    return kb.run_document_retrieval_eval(doc_id, n_samples)


@router.get("/kb/search")
def kb_search(q: str, mode: str = "hybrid", hyde: bool = False) -> dict:
    """检索试驾（HTML 前端用）。"""
    candidates = searcher.search(q, hyde=hyde, retrieval_mode=mode)
    return {"results": [
        {"chunk_id": candidate.chunk_id, "label": candidate.source_label,
         "authority": candidate.authority_level,
         "score": round(candidate.score, 4), "dense_rank": candidate.dense_rank,
         "sparse_rank": candidate.sparse_rank,
         "content": candidate.content[:200]} for candidate in candidates]}


@router.get("/kb/documents/{doc_id}/chunks")
def kb_chunks(doc_id: str, limit: int = 40) -> dict:
    return {"chunks": repo.document_chunks(doc_id, limit)}


@router.get("/kb/chunk/{chunk_id}")
def kb_chunk(chunk_id: str) -> dict:
    """单 chunk 全文（对话引用展开用）：{chunk: {id, title, page_no, section_path, content}}"""
    with repo.engine.connect() as conn:
        row = conn.execute(sql_text("""
            SELECT c.id, c.page_no, c.section_path, c.content::text, d.title
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.id = :c
        """), {"c": chunk_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"chunk 不存在：{chunk_id}")
    return {"chunk": dict(row)}
