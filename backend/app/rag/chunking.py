"""文本切分（纯函数部分）：带页码标记的 markdown → chunks。

真正落库的摄取管线在 pipeline.ingest_markdown；本模块只做切分。
输入约定：教材 OCR 后的 markdown 用 [[P123]] 标记页码（P0 阶段 OCR 脚本负责注入）。
设计文档 §5：512 token ≈ 700 字 / 64 token ≈ 90 字 overlap（中文）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PAGE_MARKER = re.compile(r"\[\[P(\d+)\]\]")


@dataclass
class Chunk:
    chunk_index: int
    page_no: int            # 起始页码（引用溯源的根基）
    section_path: str       # 单级标题（如 "3.2 目标肌群"；层级拼接未实现）
    content: str
    cert_id: str = ""
    source_type: str = "教材"     # 教材|大纲|字幕|笔记|百科
    authority_level: int = 1      # 1 官方 2 半官方 3 补充
    exam_point_ids: list = None   # type: ignore[assignment]

    def __post_init__(self):
        if self.exam_point_ids is None:
            self.exam_point_ids = []


def parse_pages(text: str) -> list[tuple[int, str]]:
    """按 [[P页码]] 标记切页。返回 [(page_no, page_text)]，无标记的文本归为 page 0。"""
    parts = PAGE_MARKER.split(text)
    pages: list[tuple[int, str]] = []
    if PAGE_MARKER.search(text) is None:
        return [(0, text.strip())]
    # split 后结构: [前置文本, 页码1, 文本1, 页码2, 文本2, ...]
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts), 2):
        page_no, body = int(parts[i]), parts[i + 1] if i + 1 < len(parts) else ""
        if body.strip():
            pages.append((page_no, body.strip()))
    return pages


def split_section(page_text: str) -> list[tuple[str, str]]:
    """按 markdown 标题切 section，返回 [(section_title, section_text)]。

    注意：当前只返回单级标题（不含父级拼接，如 "第三章/3.2 xxx"）——
    页内标题层级信息未保留，如需层级路径需扩展本函数。"""
    heading = re.compile(r"^(#{1,4})\s+(.+)$", re.M)
    matches = list(heading.finditer(page_text))
    if not matches:
        return [("", page_text)]
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
        title = m.group(2).strip()
        out.append((title, page_text[m.end():end].strip()))
    return out


def make_chunks(
    text: str,
    *,
    cert_id: str = "",
    source_type: str = "教材",
    authority_level: int = 1,
    max_chars: int = 700,
    overlap: int = 90,
) -> list[Chunk]:
    """页 → section → 滑窗切分，产出带页码与 section_path 的 chunks。

    层级切分让每块天然带上 (页码, 章节路径) 溯源元数据；
    超 max_chars 的 section 滑窗切（步长 = max_chars - overlap），
    尾部碎片（短于 overlap）并入上一块，避免产生信息量过低的碎块。
    """
    from app.config import settings
    cert_id = cert_id or settings.default_cert
    chunks: list[Chunk] = []
    idx = 0
    for page_no, page_text in parse_pages(text):
        for section, section_text in split_section(page_text):
            if not section_text:
                continue
            if len(section_text) <= max_chars:
                chunks.append(Chunk(idx, page_no, section, section_text,
                                    cert_id, source_type, authority_level))
                idx += 1
                continue
            step = max_chars - overlap
            for start in range(0, len(section_text), step):
                piece = section_text[start:start + max_chars]
                if len(piece) < overlap and chunks:  # 尾部碎片并入上一块
                    chunks[-1].content += piece
                    break
                chunks.append(Chunk(idx, page_no, section, piece,
                                    cert_id, source_type, authority_level))
                idx += 1
                if start + max_chars >= len(section_text):
                    break
    return chunks
