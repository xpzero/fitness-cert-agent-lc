#!/usr/bin/env python3
"""扫描版 PDF → 带页码标记的 markdown（macOS Vision OCR，zh-Hans + en-US）。

用法：
  .venv/bin/python scripts/ocr_pdf.py knowledge/raw/xxx.pdf knowledge/processed/xxx-带页码.md

渲染走 pymupdf，识别走系统 Vision。
依赖：pip install pyobjc-framework-Vision Pillow（本机，无外部模型下载）
"""
from __future__ import annotations

import argparse
import io
import sys

import Vision
from Foundation import NSAutoreleasePool
from PIL import Image

# 3x ≈ 216 DPI：2x（~144 DPI）下中文小字形近字错认明显（「测试」→「剥试」）
RENDER_SCALE = 3.0
# 方向自适应：竖排/旋转扫描件按总置信度四向试探，整本缓存（扫描批次方向一致）
_ROTATIONS = (0, 90, 180, 270)   # 顺时针度数
# 装订缝探测：观察点中心 x 落在页面中部窗口内，取最大横向空隙为栏分割线
_GUTTER_WINDOW = (0.3, 0.7)
_MIN_GUTTER_GAP = 0.06

_orientation: int | None = None   # 每文档缓存；worker 常驻线程处理多文档，须显式重置


def reset_orientation() -> None:
    """新文档开始时清空方向缓存（kb_worker 一进程解析多份文档）。"""
    global _orientation
    _orientation = None


def pdf_pages(path):
    """逐页渲染为 PNG bytes（RENDER_SCALE 缩放，兼顾 OCR 精度与速度）。

    渲染用 pymupdf 而非 Quartz/PDFKit：PDFKit 的 thumbnail 链路每页驻留
    ~10-30MB 且 autorelease pool 也回收不净，几百页即可累积几十 GB；
    MuPDF 渲染页级回收、内存封顶。
    """
    import pymupdf

    doc = pymupdf.open(path)
    for i in range(len(doc)):
        pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE))
        yield i + 1, pix.tobytes("png")
    doc.close()


def _rotate(png_bytes: bytes, deg_cw: int) -> bytes:
    if not deg_cw:
        return png_bytes
    trans = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[deg_cw]
    img = Image.open(io.BytesIO(png_bytes)).transpose(trans)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _ocr_observations(png_bytes: bytes) -> list[tuple]:
    """Vision 识别：[(text, confidence, cx, cy)]，坐标归一化、原点左上。

    Vision 自带 bbox 原点在左下，这里统一翻成"距顶部距离"供阅读顺序排序。
    """
    pool = NSAutoreleasePool.alloc().init()  # handler/request/results 均为 autorelease 对象
    try:
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
            png_bytes, None
        )
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        # 中文优先（歧义字符按首语言解析），en-US 兜住英文术语/整段英文
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        request.setUsesLanguageCorrection_(True)
        if not handler.performRequests_error_([request], None)[0]:
            return []
        obs = []
        for r in request.results() or []:
            cand = r.topCandidates_(1)
            if not cand:
                continue
            cand = cand[0]
            bb = r.boundingBox()
            obs.append((str(cand.string()), float(cand.confidence()),
                        bb.origin.x + bb.size.width / 2,
                        1 - bb.origin.y - bb.size.height / 2))
        return obs
    finally:
        del pool


def _detect_rotation(png_bytes: bytes) -> tuple[int, list[tuple]]:
    """四方向试探，按总置信度（块数 × 置信度）取最优。返回 (顺时针度数, 识别结果)。"""
    best_deg, best_score, best_obs = 0, -1.0, []
    for deg in _ROTATIONS:
        obs = _ocr_observations(_rotate(png_bytes, deg))
        score = sum(o[1] for o in obs)
        if score > best_score:
            best_deg, best_score, best_obs = deg, score, obs
    return best_deg, best_obs


def _layout_order(obs: list[tuple]) -> list[tuple]:
    """阅读顺序：中部空隙够宽则按装订缝分左右栏，栏内自上而下、同高从左到右。

    对开扫描（一个 PDF 页 = 书的左右两页）与双栏表格页必需——
    只按 y 排会把左右栏逐行交错成乱序。
    """
    if len(obs) >= 8:
        xs = sorted(o[2] for o in obs)
        gutter, gap = 0.5, 0.0
        for a, b in zip(xs, xs[1:]):
            if _GUTTER_WINDOW[0] <= a <= _GUTTER_WINDOW[1] and b - a > gap:
                gutter, gap = (a + b) / 2, b - a
        if gap >= _MIN_GUTTER_GAP:
            left = sorted((o for o in obs if o[2] < gutter), key=lambda o: (o[3], o[2]))
            right = sorted((o for o in obs if o[2] >= gutter), key=lambda o: (o[3], o[2]))
            return left + right
    return sorted(obs, key=lambda o: (o[3], o[2]))


def ocr_image(png_bytes: bytes) -> str:
    """单页 OCR：方向自适应（每文档探测一次）+ 装订缝阅读顺序整理。"""
    global _orientation
    if _orientation is None:
        _orientation, obs = _detect_rotation(png_bytes)
    else:
        obs = _ocr_observations(_rotate(png_bytes, _orientation))
        if len(obs) < 3:  # 个别页方向不同时重探（兜住封面/封底横图等）
            _orientation, obs = _detect_rotation(png_bytes)
    return "\n".join(o[0] for o in _layout_order(obs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    args = ap.parse_args()

    parts = []
    total_chars = 0
    for page_no, png in pdf_pages(args.pdf):
        text = ocr_image(png)
        total_chars += len(text)
        parts.append(f"\n[[P{page_no}]]\n{text}")
        print(f"P{page_no}: {len(text)} 字", file=sys.stderr)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"完成 {len(parts)} 页，共 {total_chars} 字 → {args.out}"
          + (f"（方向缓存 {_orientation}° 顺时针）" if _orientation else ""))


if __name__ == "__main__":
    main()
