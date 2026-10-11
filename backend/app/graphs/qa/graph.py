"""子图B：溯源 RAG 问答（Corrective RAG，设计文档 §4.2）——P1 完整实现。

主链路：rewrite_query(查询改写+词表扩展) → retrieve_chunks(混合检索)
→ guard(空手短路) → generate_draft(强制引用生成) → verify_citations(引用校验)，
verify_citations 三种出口：
- 通过 → format_answer（角标化+出处列表）→ 结束
- 未通过且未达重试上限 → 回 rewrite_query 改写重检（纠错环，≤ MAX_REWRITE_ROUNDS 次）
- 重试耗尽 / 检索空手 / 生成端错误 → refuse_answer / emit_error（绝不无出处作答）

独立可编译的图：`build_qa_graph()`，由 supervisor 的适配节点调用
（messages → query 进，final_answer → subgraph_output 出）。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import TypedDict

import yaml
from langgraph.graph import StateGraph

from app.llm import llm_client
from app.config import PROJECT_ROOT, settings
from app.prompts.qa import (
    ENTAIL_PROMPT,
    GENERATE_SYSTEM,
    REFUSAL_ANSWER_TEXT,
    REFUSAL_MARKER,
    REFUSAL_TEXT_PREFIX,
    REWRITE_HISTORY_PROMPT,
    REWRITE_PROMPT,
)
from app.rag.citation import extract_citations, find_missing_citations, verify_claim
from app.rag.search import searcher

MAX_REWRITE_ROUNDS = 2


def _llm_entail_batch(claim_evidence_pairs: list[tuple[str, str]]) -> list[bool | None]:
    """批量语义蕴含判定（NLI-lite）：一次调用判多句，失败返回 None 列表。

    材料是 OCR 目录/大纲碎片时，合理归纳句没有逐字对应原文——
    词面 2-gram 必然误杀。语义一致即算支持，不要求逐字复述。
    逐句调用的实测延迟不可接受（10s/句 ×6），批量一次 ~5s。
    注意：同族 LLM 自校验弱于专用 NLI 模型，后续可换 BGE-reranker 类模型。
    """
    if not claim_evidence_pairs:
        return []
    lines = "\n\n".join(
        f"{i + 1}. 论断：{claim[:160]}\n   材料：{evidence[:320]}"
        for i, (claim, evidence) in enumerate(claim_evidence_pairs)
    )
    try:
        results = llm_client.chat_json(
            [
                {
                    "role": "user",
                    "content": ENTAIL_PROMPT.format(
                        n=len(claim_evidence_pairs), lines=lines),
                }
            ],
            temperature=0.1,
        ).get("results", [])
        return ([bool(r) for r in results]
                + [None] * (len(claim_evidence_pairs) - len(results)))
    except Exception:  # noqa: BLE001 — 语义判定失败时维持词面结果
        return [None] * len(claim_evidence_pairs)


class QAState(TypedDict):
    query: str
    history: list             # 会话内上文 [{role, content}]——改写时解析指代（多轮记忆）
    rewritten_query: str
    candidates: list[
        dict
    ]  # {chunk_id, page_no, section_path, content, authority_level, score}
    verdict: str  # correct | ambiguous | wrong | error
    draft_answer: str
    cited_chunk_ids: list[str]
    final_answer: str
    refused: bool
    error: bool               # 生成端服务错误（区别于"拒答"：有 final 文案但非知识性回答）
    rewrite_rounds: int


@lru_cache
def _glossary_alias_pairs() -> list[tuple[str, str]]:
    data = yaml.safe_load((PROJECT_ROOT / "app/rag/glossary.yaml").read_text())
    return [(alias, canon) for canon, aliases in data.items() for alias in aliases]


def _expand_query_with_glossary(query: str) -> str:
    """把口语别称补充为标准术语（追加而非替换，保留原表述）。"""
    additions = [
        canon
        for alias, canon in _glossary_alias_pairs()
        if alias in query and canon not in query
    ]
    return f"{query}（{'；'.join(sorted(set(additions)))}）" if additions else query


# ---------------------------------------------------------------- nodes


def rewrite_query(state: QAState) -> dict:
    # 第二轮复用首轮改写结果（省一次 LLM 调用）；首轮才真正改写
    if state.get("rewrite_rounds", 0) > 0 and state.get("rewritten_query"):
        return {"refused": False, "rewrite_rounds": state.get("rewrite_rounds", 0)}
    query = state["query"]
    # 会话内有上文 → 带历史的改写（"它的第一步"里的"它"才有得解析）
    history = [m for m in (state.get("history") or [])
               if m.get("role") in ("user", "assistant")][-6:]
    if history:
        hist_block = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助教'}：{str(m['content'])[:300]}"
            for m in history)
        content = REWRITE_HISTORY_PROMPT.format(query=query, history=hist_block)
    else:
        content = REWRITE_PROMPT.format(query=query)
    try:
        rewritten_base = (
            llm_client.chat_json(
                [{"role": "user", "content": content}],
            ).get("rewritten")
            or query
        )
    except Exception:  # noqa: BLE001 — LLM 失败时降级为原查询
        rewritten_base = query
    # 词表扩展叠加在改写结果上（而非仅作降级）：LLM 不会主动做
    # 口语肌群名→解剖学标准名的映射，不叠加则检索仍用口语词
    return {
        "rewritten_query": _expand_query_with_glossary(rewritten_base),
        "refused": False,
        "rewrite_rounds": state.get("rewrite_rounds", 0),
    }


def retrieve_chunks(state: QAState) -> dict:
    # HyDE 多一次 LLM 调用：首轮用（收益大），改写重试轮跳过（省时）
    use_hyde = state.get("rewrite_rounds", 0) == 0
    candidates = searcher.search(state["rewritten_query"], hyde=use_hyde)
    return {
        "candidates": [c.__dict__ | {"source_label": c.source_label}
                       for c in candidates]
    }


def guard_no_candidates(state: QAState) -> dict:
    """检索空手短路（启发式，无 LLM）。

    原 LLM 判级实测 9-11s（与 generate 同量级），且其"能否回答"判断与
    generate_draft 的 REFUSAL_MARKER + verify_citations 的引用校验功能重叠
    ——去重后只保留短路作用：候选为空 → wrong（直接拒答），否则放行给生成链路。
    """
    if not state["candidates"]:
        return {"verdict": "wrong"}
    return {"verdict": "correct"}


def generate_draft(state: QAState) -> dict:
    # 材料预算：前 6 个候选、每块截 500 字——足够支撑回答又控住 prompt 长度
    blocks = "\n\n".join(
        f"[{candidate['chunk_id']}] 来源:{candidate.get('source_label', '')}\n"
        f"{candidate['content'][:500]}"
        for candidate in state["candidates"][:6]
    )
    prompt = [
        {"role": "system", "content": GENERATE_SYSTEM},
        {"role": "user",
         "content": f"问题：{state['rewritten_query']}\n\n材料：\n{blocks}"},
    ]
    try:
        # 实时吐字：经 LangGraph custom stream 穿透到 SSE（不支持时静默降级）
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        token_parts: list[str] = []
        for token in llm_client.chat_gen_stream(prompt, max_tokens=1500):
            token_parts.append(token)
            try:
                writer({"token": token})
            except Exception:  # noqa: BLE001 — 非 astream 上下文无 writer
                pass
        draft = "".join(token_parts)
    except Exception as e:  # noqa: BLE001
        # 生成端错误必须透传到最终输出——不能落进 refuse 分支被"无法溯源"话术覆盖
        return {
            "draft_answer": REFUSAL_MARKER,
            "cited_chunk_ids": [],
            "final_answer": f"生成服务暂时不可用（稍后重试）：{str(e)[:120]}",
            "verdict": "error",
        }
    return {"draft_answer": draft, "cited_chunk_ids": extract_citations(draft)}


def verify_citations(state: QAState) -> dict:
    """引用校验（Corrective RAG 的关键闸门）：答案必须真的"长在"材料上。

    三步检查：
    1. REFUSAL_MARKER：生成端自己标记了无法作答 → wrong（直接拒答路径）
    2. 引用存在性：draft_answer 里的 [chunk:ID] 必须都在本轮候选集中（防编造 id）
    3. 支撑度抽查：逐条引用句先做词面快筛（零成本），不过关的合并成一次
       批量语义判定（NLI-lite，控延迟），支持率 ≥ min_citation_support_ratio 才放行

    任一步不过 → ambiguous + rewrite_rounds+1，回改写环节重检；
    重试耗尽由 route_after_verify 路由到拒答。
    """
    draft = state["draft_answer"]
    if REFUSAL_MARKER in draft and not state["cited_chunk_ids"]:
        return {"verdict": "wrong"}
    known_chunk_ids = {candidate["chunk_id"] for candidate in state["candidates"]}
    missing = find_missing_citations(draft, known_chunk_ids)
    rounds = state.get("rewrite_rounds", 0)

    # 引用句抽查：先词面快筛，不过关的合并成一次批量语义判定（控延迟与成本）
    supported = checked = 0
    candidates_by_id = {candidate["chunk_id"]: candidate
                        for candidate in state["candidates"]}
    nli_fallback_pairs: list[tuple[str, str]] = []
    for cid in state["cited_chunk_ids"]:
        # 编造/不在候选集的 id（如双前缀 doc-doc-…）已由 find_missing_citations
        # 记入 missing 走 ambiguous；这里跳过，避免对不存在的 id 查字典崩溃
        if cid not in candidates_by_id:
            continue
        for sent in _sentences_citing(draft, cid):
            checked += 1
            if verify_claim(
                sent, candidates_by_id[cid]["content"],
                min_support=settings.lexical_support_min
            )["supported"]:
                supported += 1
            elif len(nli_fallback_pairs) < settings.nli_fallback_max_claims:
                nli_fallback_pairs.append(
                    (sent, candidates_by_id[cid]["content"]))
    if nli_fallback_pairs:
        for ok in _llm_entail_batch(nli_fallback_pairs):
            if ok:
                supported += 1
    all_checks_passed = (
        (not missing)
        and state["cited_chunk_ids"]
        and (checked == 0
             or supported / checked >= settings.min_citation_support_ratio)
    )
    if all_checks_passed:
        return {"verdict": "correct"}
    return {
        "verdict": "ambiguous",
        "rewrite_rounds": rounds + 1,
        "final_answer": f"（内部校验未通过：缺引用 {missing or '无'}，"
        f"支持率 {supported}/{checked}）"
        if missing or checked
        else "",
    }


def refuse_answer(state: QAState) -> dict:
    return {"refused": True, "final_answer": REFUSAL_ANSWER_TEXT}


def format_answer(state: QAState) -> dict:
    """输出格式化：长引用标记 [chunk:ID] 换成短角标，文末附出处清单。"""
    candidates_by_id = {candidate["chunk_id"]: candidate
                        for candidate in state["candidates"]}
    draft_text = state["draft_answer"]
    footnote_lines = []
    for cid in state["cited_chunk_ids"]:
        candidate = candidates_by_id.get(cid)
        if candidate:
            footnote_lines.append(
                f"[{cid[:14]}…] {candidate.get('source_label', '')}")
            draft_text = draft_text.replace(f"[chunk:{cid}]", f"[{cid[:14]}…]")
    return {"final_answer": draft_text + (
        "\n\n📚 出处：\n" + "\n".join(footnote_lines) if footnote_lines else "")}


def _sentences_citing(draft: str, chunk_id: str) -> list[str]:
    """取包含该引用标记的句子（供支撑度抽查）；跳过 <8 字的结构行（标题/列表符）。"""
    marker = f"[chunk:{chunk_id}]"
    sents = [s.strip() for s in draft.replace("。", "。\n").splitlines()
             if marker in s]
    return [s for s in sents if len(re.sub(r"[^\w]", "", s)) >= 8] or (
        [draft] if marker in draft else []
    )


# ---------------------------------------------------------------- edges


def route_after_verify(state: QAState) -> str:
    if state["verdict"] == "error":  # 服务错误 → 直接出错误说明，不走拒答话术
        return "emit_error"
    if state.get("rewrite_rounds", 0) >= MAX_REWRITE_ROUNDS:
        return "refuse_answer"
    return {"correct": "format_answer", "ambiguous": "rewrite_query",
            "wrong": "refuse_answer"}.get(state["verdict"], "rewrite_query")


def emit_error(state: QAState) -> dict:
    """透传生成端错误（final_answer 已由 generate_draft 写入）。

    error 与 refused 分离：服务错误不是"拒答"，下游（前端/观测）可区分两种语义。"""
    return {"error": True}


def build_qa_graph():
    """装配 Corrective RAG 图。verify_citations → rewrite_query 边构成纠错环：
    校验不过带着更高 rewrite_rounds 重走检索，耗尽 MAX_REWRITE_ROUNDS 后拒答。"""
    g = StateGraph(QAState)
    g.add_node("rewrite_query", rewrite_query)
    g.add_node("retrieve_chunks", retrieve_chunks)
    g.add_node("guard", guard_no_candidates)
    g.add_node("generate_draft", generate_draft)
    g.add_node("verify_citations", verify_citations)
    g.add_node("refuse_answer", refuse_answer)
    g.add_node("emit_error", emit_error)
    g.add_node("format_answer", format_answer)
    g.set_entry_point("rewrite_query")
    g.add_edge("rewrite_query", "retrieve_chunks")
    g.add_edge("retrieve_chunks", "guard")
    g.add_edge("guard", "generate_draft")
    g.add_edge("generate_draft", "verify_citations")
    g.add_conditional_edges(
        "verify_citations",
        route_after_verify,
        {
            "format_answer": "format_answer",
            "rewrite_query": "rewrite_query",
            "refuse_answer": "refuse_answer",
            "emit_error": "emit_error",
        },
    )
    g.add_edge("format_answer", "__end__")
    g.add_edge("refuse_answer", "__end__")
    g.add_edge("emit_error", "__end__")
    return g.compile()
