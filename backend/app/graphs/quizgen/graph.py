"""子图C：AI 出题（防幻觉核心，设计文档 §4.3）——P2 完整实现。

入库闸门链：逐字 grounding（≥evidence_min_similarity）→ 语义查重 → 质量分（只打分）
→ 对抗评审（W2：双 persona 攻击，幸存者入库）。
verified=False 的题进入人工审核队列，永不出现在用户侧。

结构：generate 产出 QuestionDraft（数据类，闸门链中的统一载体）→
四个门闸类依次过滤（每道返回 passed/rejected），全部通过才入库。
"""
from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import StateGraph
from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from app.llm import llm_client
from app.config import settings
from app.db import get_engine
from app.prompts.quizgen import (
    ADVERSARIAL_GUESSER_PROMPT,
    ADVERSARIAL_NITPICK_PROMPT,
    QUESTION_GEN_SYSTEM,
    QUALITY_RUBRIC_PROMPT,
)
from app.rag.citation import verbatim_coverage
from app.rag.search import searcher
from app.services.repositories import repo
from app.tools.grader import resolve_answer_key


@dataclass
class QuestionDraft:
    """一道待审题目在闸门链中的状态（生成阶段填题面，门闸逐步填校验结果）。"""
    point_id: str
    point_title: str
    question_type: str = ""
    stem: str = ""
    options: dict = field(default_factory=dict)
    answer: str = ""
    explanation: str = ""
    evidence_text: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)
    difficulty: int = 3
    # —— 闸门链填充 ——
    error: str = ""            # 非空 = 生成阶段已失败，直接走拒绝路径
    grounding_score: float = 0.0  # 闸门1：逐字定位比例
    quality_score: float = 0.0    # 闸门3：rubric 均分
    verified: bool = False
    question_id: str = ""


class QuizGenState(TypedDict):
    cert_id: str
    n_points: int
    exam_points: list[dict]     # 选中的考点 {id, title, chapter}
    drafts: list[QuestionDraft]
    accepted: list[QuestionDraft]  # 过全部闸门的题（已入库）
    rejected: list[dict]         # {stem, reason}
    coverage_delta: list[str]    # 本轮新覆盖的考点 id
    exclude_points: list[str]    # 批量出题时跳过重复失败的考点
    seed_points: list[str]       # 定向出题（W4 变式题）：指定考点 id，跳过覆盖分析
    question_type: str           # 定向题型（mock=四选一单选）；空 = 按索引轮换


# ---------------------------------------------------------------- nodes

def pick_points(state: QuizGenState) -> dict:
    """覆盖分析：优先取"还没有题目的考点"，其次取题最少的考点。

    seed_points（W4 教练变式题）：定向出题模式，跳过覆盖分析直接用指定考点。
    SQL 要点：只取叶子考点（parent_id <> ''）；`q.exam_point_ids ? ep.id`
    是 jsonb 包含查询（题目→考点的多对多在 jsonb 列上）；按已有题数升序、
    考点权重降序——新覆盖优先、重要考点次之。
    """
    engine = get_engine()
    cert = state["cert_id"]
    seed = state.get("seed_points") or []
    if seed:
        with engine.connect() as conn:
            rows = conn.execute(sql_text(
                "SELECT id, title, chapter FROM exam_points "
                "WHERE id = ANY(:ids) AND parent_id <> ''"),
                {"ids": seed}).mappings().all()
        return {"exam_points": [dict(r) for r in rows], "accepted": [],
                "rejected": [], "coverage_delta": []}
    with engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT ep.id, ep.title, ep.chapter, count(q.id) AS n
            FROM exam_points ep
            LEFT JOIN questions q ON q.exam_point_ids ? ep.id AND q.verified
            WHERE ep.cert_id = :cert AND ep.parent_id <> ''
              AND NOT (ep.id = ANY(:exclude))
            GROUP BY ep.id, ep.title, ep.chapter, ep.weight
            ORDER BY n ASC, ep.weight DESC
            LIMIT :n
        """), {"cert": cert, "n": state.get("n_points", 3),
               "exclude": state.get("exclude_points", [])}).mappings().all()
    return {"exam_points": [dict(r) for r in rows], "accepted": [],
            "rejected": [], "coverage_delta": []}


def _generate_one_draft(point: dict, qtype: str) -> QuestionDraft:
    """单考点出题（W1 并行 worker 内执行）：检索 → LLM → 草稿（失败则带 error）。"""
    # 出题检索不用 HyDE：考点标题本身即标准术语，多一次 LLM 无收益
    candidates = searcher.search(point["title"], hyde=False)[:3]
    if not candidates:
        return QuestionDraft(point["id"],
                             f"{point['chapter']} / {point['title']}",
                             error="no_corpus")
    blocks = "\n\n".join(f"[{cand.chunk_id}] {cand.content[:700]}"
                         for cand in candidates)
    prompt = [
        {"role": "system", "content": QUESTION_GEN_SYSTEM},
        {"role": "user",
         "content": f"考点：{point['chapter']} / {point['title']}\n"
                    f"题型：{qtype}\n\n材料：\n{blocks}"},
    ]
    resp = None
    for attempt, (temperature, max_tokens) in enumerate(((0.4, 2000), (0.2, 2000))):
        try:
            resp = llm_client.chat_json(prompt, model_tier="gen",
                                        temperature=temperature,
                                        max_tokens=max_tokens)
            break
        except Exception:  # noqa: BLE001 — 截断/围栏等解析失败 → 低温重试一次
            if attempt:
                resp = None
    if resp and resp.get("stem") and resp.get("answer"):
        options = resp.get("options") or {}
        return QuestionDraft(
            point_id=point["id"],
            point_title=f"{point['chapter']} / {point['title']}",
            question_type=str(resp.get("type", "")), stem=resp["stem"],
            options=options,
            # 判分/前端都用选项字母，判断题模型爱答「对/错」——入库前归一
            answer=resolve_answer_key(resp["answer"], options),
            explanation=resp.get("explanation", ""),
            evidence_text=resp.get("evidence_text", ""),
            source_chunk_ids=resp.get("source_chunk_ids") or [],
            difficulty=int(resp.get("difficulty") or 3))
    return QuestionDraft(point["id"],
                         f"{point['chapter']} / {point['title']}",
                         error="生成两次均解析失败")


def generate_drafts(state: QuizGenState) -> dict:
    """逐考点生成草稿（W1：线程池并行，结果按考点原序组装）。

    各考点相互独立（检索 + LLM 均 IO-bound）；题型按考点序号轮换
    single/judge/multi，在提交前按索引确定——并行下顺序与题型分配仍确定。
    每个考点独立容错：失败记入 draft.error，由闸门统一走拒绝路径。
    """
    points = state["exam_points"]
    forced = state.get("question_type") or ""
    # 定向题型（mock 场景 single-only：四大证笔试均为四选一单选）优先于轮换
    qtypes = ([forced] * len(points) if forced
              else [("single", "judge", "multi")[i % 3] for i in range(len(points))])
    workers = max(1, settings.quizgen_parallel_workers)
    if workers == 1 or len(points) <= 1:
        drafts = [_generate_one_draft(p, q)
                  for p, q in zip(points, qtypes)]
    else:
        with ThreadPoolExecutor(
                max_workers=min(workers, len(points))) as pool:
            futures = [pool.submit(_generate_one_draft, p, q)
                       for p, q in zip(points, qtypes)]
            drafts = [f.result() for f in futures]  # futures 序即考点原序
    return {"drafts": drafts}


# ---------------------------------------------------------------- 门闸

# 题干悬空引用：指到了考生看不到的表/图（self_contained_check 用）
DANGLING_REF_RE = re.compile(r"表\s*\d|图\s*\d|如下[表图]|如[表图]所示|见[表图]|下[表图]所示")

class GroundingGate:
    """闸门1：evidence_text 必须在其 source chunk 中逐字可定位（防幻觉）。

    对每道题取"定位比例最高的那个 chunk"作为 grounding 分——
    作者引用了哪个 chunk 不重要，材料里真的有这句话才算数。
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def filter(self, drafts: list[QuestionDraft]) -> tuple[list[QuestionDraft], list[dict]]:
        chunks_by_id = repo.chunks_by_ids(
            [cid for d in drafts for cid in d.source_chunk_ids])
        passed, rejected = [], []
        for d in drafts:
            if d.error:
                rejected.append({"stem": d.stem or d.point_id, "reason": f"生成失败: {d.error}"})
                continue
            best_ratio = max((verbatim_coverage(d.evidence_text, chunks_by_id[cid].content)
                              for cid in d.source_chunk_ids if cid in chunks_by_id),
                             default=0.0)
            if best_ratio >= settings.evidence_min_similarity:
                d.grounding_score = round(best_ratio, 3)
                passed.append(d)
            else:
                rejected.append({"stem": d.stem or "?",
                                 "reason": f"grounding {best_ratio:.2f} < "
                                           f"{settings.evidence_min_similarity}"})
        return passed, rejected


class DedupeGate:
    """闸门2：与库内已有题干语义查重（word_similarity > quiz_dedupe_similarity 视为重复）。"""

    def __init__(self, engine: Engine):
        self.engine = engine

    def filter(self, drafts: list[QuestionDraft]) -> tuple[list[QuestionDraft], list[dict]]:
        passed, rejected = [], []
        with self.engine.begin() as conn:  # 单连接跑完本批
            for d in drafts:
                dup_row = conn.execute(sql_text(
                    "SELECT id FROM questions WHERE word_similarity(:stem, stem) > :t LIMIT 1"
                ), {"stem": d.stem, "t": settings.quiz_dedupe_similarity}).first()
                if dup_row:
                    rejected.append({"stem": d.stem[:60],
                                     "reason": f"与已有题 {dup_row[0]} 重复"})
                else:
                    passed.append(d)
        return passed, rejected


class QualityGate:
    """闸门3：小模型 rubric 打分（清晰/答案唯一/干扰项合理/依据充分）。

    W2 起只打分不插库：打分通过的题交 AdversarialGate 攻击，
    幸存者才由 insert_question 入库（打分通过 ≠ 直接入库）。
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def filter(self, drafts: list[QuestionDraft],
               cert_id: str) -> tuple[list[QuestionDraft], list[dict]]:
        if not drafts:
            return [], []
        lines = "\n\n".join(
            f"{i+1}. 题干：{d.stem}\n   选项：{json.dumps(d.options, ensure_ascii=False)}"
            f"\n   答案：{d.answer}\n   依据：{d.evidence_text[:150]}"
            for i, d in enumerate(drafts))
        try:
            scores = llm_client.chat_json(
                [{"role": "user", "content": QUALITY_RUBRIC_PROMPT.format(lines=lines)}],
                temperature=0.1,
            ).get("scores", [])
        except Exception:  # noqa: BLE001 — 打分失败按 3.5 处理（进人工队列）
            scores = [3.5] * len(drafts)
        min_quality_score = settings.quiz_quality_min_score
        passed, rejected = [], []
        for i, d in enumerate(drafts):
            # 模型漏打/打分失败按 3.5（低于闸门 4.0）——宁缺勿滥，进人工队列也不误放行
            score = float(scores[i]) if i < len(scores) else 3.5
            d.quality_score = round(score, 2)
            d.verified = score >= min_quality_score
            if not d.verified:
                rejected.append({"stem": d.stem[:60],
                                 "reason": f"质量分 {score} < {min_quality_score}"
                                           "（进人工队列前先不入题库）"})
                continue
            passed.append(d)
        return passed, rejected


def insert_question(engine: Engine, d: QuestionDraft, cert_id: str) -> None:
    """过全部闸门的题入库（原 QualityGate 私有方法上移，供对抗闸通过后调用）。"""
    with engine.begin() as conn:
        conn.execute(sql_text("""
            INSERT INTO questions (id, cert_id, type, stem, options, answer, explanation,
                                   source_chunk_ids, evidence_text, exam_point_ids,
                                   difficulty, origin, verified, quality_score)
            VALUES (:id, :cert_id, :type, :stem, CAST(:options AS jsonb), :answer, :explanation,
                    CAST(:source_chunk_ids AS jsonb), :evidence_text, CAST(:exam_point_ids AS jsonb),
                    :difficulty, 'AI生成', true, :quality_score)
        """), {
            "id": d.question_id, "cert_id": cert_id, "type": d.question_type,
            "stem": d.stem, "options": json.dumps(d.options, ensure_ascii=False),
            "answer": d.answer, "explanation": d.explanation,
            "source_chunk_ids": json.dumps(d.source_chunk_ids),
            "evidence_text": d.evidence_text,
            "exam_point_ids": json.dumps([d.point_id]),
            "difficulty": d.difficulty, "quality_score": d.quality_score,
        })


class AdversarialGate:
    """闸门4（W2）：对抗评审——双 persona 攻击，攻不破的题才入库。

    与 rubric 打分的本质区别：打分问"这题几分"（评审员视角，同族高抬贵手），
    对抗问"这题哪里能被击破"（考生视角，胜利条件是找到具体缺陷）。

    - 较真考生：可见题面/选项/标答/依据，任务=找可投诉的硬伤（答案不唯一/
      歧义/信息不足/与依据矛盾）。投诉必须逐字引用选项原文（quote 程序校验，
      引用定位不到的投诉无效）——防 critic 编造指控。severity ≥ 阈值的有效
      投诉 → 拒绝。
    - 蒙题考生：只给选项不给题干，凭选项特征猜答案；猜中且置信度 ≥ 阈值
      → 题可猜测 → 拒绝。判断题（对/错二选一）天然可猜，豁免本项。
    - adversarial_gate_enabled=False：全数放行，行为与旧闸门链完全一致。
    - LLM 失败 fail-open（放行）——前三道闸仍在，对抗缺席不阻塞管线。
    insert=False 供评测/单测使用：走判定但不写库。
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def filter(self, drafts: list[QuestionDraft], cert_id: str, *,
               insert: bool = True) -> tuple[list[QuestionDraft], list[dict]]:
        if not drafts:
            return [], []
        if not settings.adversarial_gate_enabled:
            passed = self._admit(drafts, cert_id, insert=insert)
            return passed, []
        reasons = self._attack(drafts)
        passed, rejected = [], []
        for d, reason in zip(drafts, reasons):
            if reason:
                rejected.append({"stem": d.stem[:60], "reason": reason})
            else:
                passed.extend(self._admit([d], cert_id, insert=insert))
        return passed, rejected

    def _admit(self, drafts: list[QuestionDraft], cert_id: str, *,
               insert: bool) -> list[QuestionDraft]:
        for d in drafts:
            d.question_id = "q-" + uuid.uuid4().hex[:10]
            if insert:
                insert_question(self.engine, d, cert_id)
        return drafts

    # ------------------------------------------------------------ 双 persona
    def _attack(self, drafts: list[QuestionDraft]) -> list[str | None]:
        """返回每题的拒绝原因（None = 幸存）。

        逐题调用而非批量：实测批量 ≥10 题时 persona 注意力稀释、频繁空手
        （对歧义题漏报）；单题聚焦时投诉/猜测质量稳定。真实管线每轮幸存
        者通常 ≤4 题，2 次快档调用/题的成本可接受。
        """
        return [self._attack_one(d) for d in drafts]

    def _attack_one(self, d: QuestionDraft) -> str | None:
        # persona 1：较真考生（可见题面/选项/标答/依据，任务=找可投诉的硬伤）
        lines = (f"1. 题干：{d.stem}\n   选项：{json.dumps(d.options, ensure_ascii=False)}"
                 f"\n   标答：{d.answer}\n   依据：{d.evidence_text[:120]}")
        try:
            complaints = llm_client.chat_json(
                [{"role": "user",
                  "content": ADVERSARIAL_NITPICK_PROMPT.format(lines=lines)}],
                temperature=0.1,
            ).get("complaints", [])
        except Exception:  # noqa: BLE001 — 对抗缺席 fail-open
            complaints = []
        for c in complaints:
            quote = str(c.get("quote", "")).strip()
            severity = float(c.get("severity", 0) or 0)
            # quote 可摘自题干（缺限定类硬伤）或选项（歧义类硬伤），逐字可定位才算数
            located = quote and (quote in d.stem
                                 or any(quote in str(v) for v in d.options.values()))
            if severity >= settings.adversarial_severity_min and located:
                return (f"被较真考生投诉：{str(c.get('reason', ''))[:80]}"
                        f"（选项 {c.get('option', '?')}）")

        # persona 2：蒙题考生（只给选项不给题干；判断题二选一天然可猜，豁免）
        if d.question_type == "judge":
            return None
        opt_lines = f"1. 选项：{json.dumps(d.options, ensure_ascii=False)}"
        try:
            guesses = llm_client.chat_json(
                [{"role": "user",
                  "content": ADVERSARIAL_GUESSER_PROMPT.format(lines=opt_lines)}],
                temperature=0.1,
            ).get("guesses", [])
        except Exception:  # noqa: BLE001
            guesses = []
        for g in guesses:
            pick = "".join(sorted(str(g.get("pick", "")).upper()))
            answer = "".join(sorted(d.answer.upper()))
            confidence = float(g.get("confidence", 0) or 0)
            if (pick and pick == answer
                    and confidence >= settings.guesser_confidence_min):
                return ("蒙题测试命中：不看题干猜对标答"
                        f"（策略：{str(g.get('strategy', ''))[:60]}）")
        return None


def self_contained_check(state: QuizGenState) -> dict:
    """闸门0（零成本）：题干自包含——LLM 爱把材料里的『表13.3』『如图』抄进
    题干，但页面不会展示原表，悬空引用对考生是不可解噪声，直接拒绝。"""
    passed, rejected = [], []
    for d in state["drafts"]:
        if DANGLING_REF_RE.search(d.stem or ""):
            rejected.append({"stem": (d.stem or "?")[:60],
                             "reason": "题干引用了未呈现的表/图（悬空引用）"})
        else:
            passed.append(d)
    return {"drafts": passed, "rejected": rejected}


def grounding_check(state: QuizGenState) -> dict:
    passed, rejected = GroundingGate(get_engine()).filter(state["drafts"])
    return {"accepted": passed,
            "rejected": state.get("rejected", []) + rejected}


def dedupe(state: QuizGenState) -> dict:
    passed, rejected = DedupeGate(get_engine()).filter(state["accepted"])
    return {"accepted": passed, "rejected": state["rejected"] + rejected}


def quality_gate(state: QuizGenState) -> dict:
    passed, rejected = QualityGate(get_engine()).filter(state["accepted"],
                                                        state["cert_id"])
    return {"accepted": passed, "rejected": state["rejected"] + rejected}


def adversarial_gate(state: QuizGenState) -> dict:
    passed, rejected = AdversarialGate(get_engine()).filter(state["accepted"],
                                                            state["cert_id"])
    return {"accepted": passed, "rejected": state["rejected"] + rejected}


def coverage_report(state: QuizGenState) -> dict:
    """本轮通过的题目给覆盖率带来的增量（考点 id 去重）。"""
    delta = sorted({d.point_id for d in state["accepted"]})
    return {"coverage_delta": delta}


# ---------------------------------------------------------------- graph

def build_quizgen_graph():
    """线性闸门链。闸门顺序按成本递增刻意安排：
    grounding（纯本地计算）→ 查重（每题 1 次 SQL）→ 质量分（1 次批量 LLM）
    → 对抗（2 次批量 LLM，只攻击前三关幸存者）——便宜的闸门先淘汰坏题，
    贵的闸门只需审幸存者；入库只发生在 adversarial 通过之后。"""
    from app.graphs.common import build_linear_graph

    return build_linear_graph(QuizGenState, {
        "pick_points": pick_points,
        "generate_drafts": generate_drafts,
        "self_contained": self_contained_check,
        "grounding": grounding_check,
        "dedupe": dedupe,
        "quality": quality_gate,
        "adversarial": adversarial_gate,
        "coverage": coverage_report,
    })
