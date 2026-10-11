"""引用校验器（纯函数部分）。

三条闸门（设计文档 §4.2/§4.3）：
1. 生成文本中的 [chunk:ID] 引用必须真实存在
2. 关键断言须被所引 chunk 支持：lexical 重叠兜底，NLI 模型可选注入
3. 出题的 evidence_text 必须在源 chunk 中逐字可定位（verbatim_coverage）

术语约定：chunk_text=检索源材料原文；quote=待核实的摘抄句。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

CITE_PATTERN = re.compile(r"\[chunk:([\w-]+)\]")


def _clean(s: str) -> str:
    """归一化：仅保留 \\w 字符（CJK/字母/数字），剔除空白/标点/markdown 装饰。"""
    return re.sub(r"[^\w]+", "", s)


def extract_citations(text: str) -> list[str]:
    """按出现顺序去重提取引用的 chunk_id。"""
    seen: list[str] = []
    for cid in CITE_PATTERN.findall(text):
        if cid not in seen:
            seen.append(cid)
    return seen


def find_missing_citations(text: str, known_ids: set[str]) -> list[str]:
    """返回文本中引用了但库里不存在的 chunk_id（应打断生成重试）。"""
    return [cid for cid in extract_citations(text) if cid not in known_ids]


def _lexical_support(claim: str, chunk_text: str) -> float:
    """词覆盖率（NLI 不可用时的兜底）。清洗后只保留 \w 字符（CJK/字母/数字），
    剔除 markdown 装饰（**、-、①）与标点，中文按 2-gram。"""
    def tokens(s: str) -> set[str]:
        s = re.sub(r"[^\w]+", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    claim_b, evid_b = tokens(claim), tokens(chunk_text)
    if not claim_b:
        return 0.0
    return len(claim_b & evid_b) / len(claim_b)


def verify_claim(claim: str, chunk_text: str, *, nli_fn=None,
                 min_support: float = 0.35) -> dict:
    """单个断言 vs 单个 chunk。nli_fn(claim, chunk_text) -> bool 时优先用 NLI。"""
    if nli_fn is not None:
        return {"supported": bool(nli_fn(claim, chunk_text)), "score": 1.0,
                "method": "nli"}
    score = _lexical_support(claim, chunk_text)
    return {"supported": score >= min_support, "score": round(score, 3),
            "method": "lexical"}


def verbatim_coverage(quote: str, chunk_text: str) -> float:
    """quote 是否在 chunk_text 中逐字可定位。

    双侧清洗后用最长匹配块占 quote 长度的比例衡量——出题防幻觉的
    量化闸门（设计文档 §4.3 grounding_check，调用方以 ≥0.9 视为逐字成立）。
    返回 0~1 的定位比例。
    """
    ev, ct = _clean(quote), _clean(chunk_text)
    if len(ev) < 6:
        return 0.0
    matcher = SequenceMatcher(None, ev, ct, autojunk=False)
    matched = sum(b.size for b in matcher.get_matching_blocks())
    return matched / len(ev)
