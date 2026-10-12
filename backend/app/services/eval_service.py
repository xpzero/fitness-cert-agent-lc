"""评测中心：金标准用例管理 + 后台评测任务 + 结果存档。

- eval_cases 表：四套金标准（retrieval/intent/citation/adversarial）迁 DB，
  支持 UI 增删改；jsonl 文件仍是 CI 的快照源，import_cases() 双向兼容
- eval_runs 表：每次运行的结果（指标 + 明细），页面展示最近一次与历史
- 后台任务：线程池单发，轮询查状态（复用 kb_worker 的 phase 模式，
  不引入队列基建）
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text as sql_text

from app.db import database

KINDS = ("retrieval", "intent", "citation", "adversarial")
GATES = {  # 门槛（与 CI 一致）
    "retrieval": {"metric": "recall@5", "min": 0.75},
    "intent": {"metric": "accuracy", "min": 0.92},
    "citation": {"metric": "hit_rate", "min": 0.95},
    "adversarial": {"metric": "catch_rate", "min": 0.70},
}
_JSONL = {
    "retrieval": "rag_qa_auto.jsonl",
    "intent": "intent_labeled.jsonl",
    "citation": "rag_qa_citation.jsonl",
    "adversarial": "adversarial_cases.jsonl",
}

_pool = ThreadPoolExecutor(max_workers=1)
_tasks: dict[str, dict] = {}  # run_id -> {kind, phase, progress, run_id}


def init_eval_tables() -> None:
    from app.db import init_db

    init_db()
    with database.engine.begin() as conn:
        conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS eval_cases (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload JSONB NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE
            )"""))
        conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                metrics JSONB NOT NULL,
                passed BOOLEAN NOT NULL,
                detail JSONB,
                progress INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""))
        conn.execute(sql_text(
            "ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS progress INT NOT NULL DEFAULT 0"))


def import_cases(kind: str, filename: str | None = None) -> int:
    """从 jsonl 快照导入该类别用例（按 id 去重，已有不覆盖）。返回新增数。"""
    from app.config import PROJECT_ROOT

    path = PROJECT_ROOT / "eval/golden" / (filename or _JSONL[kind])
    added = 0
    with database.engine.begin() as conn:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            cid = case.get("id") or f"{kind}-{uuid.uuid4().hex[:10]}"
            r = conn.execute(sql_text(
                "INSERT INTO eval_cases (id, kind, payload) "
                "VALUES (:i, :k, CAST(:c AS jsonb)) "
                "ON CONFLICT (id) DO NOTHING RETURNING id"),
                {"i": cid, "k": kind,
                 "c": json.dumps(case, ensure_ascii=False)}).first()
            if r:
                added += 1
    return added


def list_cases(kind: str) -> list[dict]:
    rows = database.engine.connect().execute(sql_text(
        "SELECT id, payload, enabled FROM eval_cases WHERE kind = :k "
        "ORDER BY id"), {"k": kind}).mappings().all()
    return [{"id": r["id"], "enabled": r["enabled"], **r["payload"]}
            for r in rows]


def upsert_case(kind: str, case: dict) -> dict:
    cid = case.get("id") or f"{kind}-{uuid.uuid4().hex[:10]}"
    with database.engine.begin() as conn:
        conn.execute(sql_text(
            "INSERT INTO eval_cases (id, kind, payload) VALUES (:i, :k, CAST(:c AS jsonb)) "
            "ON CONFLICT (id) DO UPDATE SET payload = CAST(:c AS jsonb)"),
            {"i": cid, "k": kind, "c": json.dumps({**case, "id": cid}, ensure_ascii=False)})
    return {"id": cid}


def delete_case(case_id: str) -> dict:
    with database.engine.begin() as conn:
        conn.execute(sql_text("DELETE FROM eval_cases WHERE id = :i"), {"i": case_id})
    return {"id": case_id, "deleted": True}


# ---------------------------------------------------------------- 运行

def run_eval(kind: str) -> str:
    """提交评测任务（异步），返回 run_id。"""
    if kind not in KINDS:
        raise KeyError(f"未知评测类别：{kind}")
    init_eval_tables()
    if not list_cases(kind):
        import_cases(kind)
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    _tasks[run_id] = {"kind": kind, "phase": "running", "progress": 0}
    with database.engine.begin() as conn:  # 运行中即落库（重启后可查）
        conn.execute(sql_text(
            "INSERT INTO eval_runs (id, kind, metrics, passed, progress) "
            "VALUES (:i, :k, '{}'::jsonb, false, 0)"),
            {"i": run_id, "k": kind})
    _pool.submit(_execute, run_id, kind)
    return run_id


def get_task(run_id: str) -> dict | None:
    if run_id in _tasks:
        return _tasks[run_id]
    # 进程重启后：从库恢复状态；未完成的标记为中断（不再运行）
    row = database.engine.connect().execute(sql_text(
        "SELECT kind, progress, passed, metrics::text FROM eval_runs "
        "WHERE id = :i"), {"i": run_id}).first()
    if not row:
        return None
    if row[1] >= 100:
        return {"kind": row[0], "phase": "done", "progress": 100,
                "metrics": json.loads(row[3])}
    return {"kind": row[0], "phase": "interrupted", "progress": row[1],
            "error": "服务重启导致评测中断，请重新运行"}


def latest_runs() -> list[dict]:
    rows = database.engine.connect().execute(sql_text("""
        SELECT DISTINCT ON (kind) kind, id, metrics, passed, created_at
        FROM eval_runs ORDER BY kind, created_at DESC
    """)).mappings().all()
    return [dict(r) for r in rows]


def run_history(kind: str, limit: int = 20) -> list[dict]:
    rows = database.engine.connect().execute(sql_text(
        "SELECT id, metrics, passed, created_at FROM eval_runs "
        "WHERE kind = :k ORDER BY created_at DESC LIMIT :n"),
        {"k": kind, "n": limit}).mappings().all()
    return [dict(r) for r in rows]


def _persist_progress(run_id: str, progress: int) -> None:
    try:
        with database.engine.begin() as conn:
            conn.execute(sql_text(
                "UPDATE eval_runs SET progress = :p WHERE id = :i"),
                {"p": progress, "i": run_id})
    except Exception:  # noqa: BLE001 — 进度写失败不影响评测本身
        pass


def _finish(run_id: str, kind: str, metrics: dict, passed: bool,
            detail: dict | None) -> None:
    with database.engine.begin() as conn:
        conn.execute(sql_text(
            "UPDATE eval_runs SET metrics = CAST(:m AS jsonb), passed = :p, "
            "detail = CAST(:d AS jsonb), progress = 100 WHERE id = :i"),
            {"i": run_id, "p": passed,
             "m": json.dumps(metrics, ensure_ascii=False),
             "d": json.dumps(detail or {}, ensure_ascii=False)})
    _tasks[run_id].update(phase="done", progress=100)


def _execute(run_id: str, kind: str) -> None:
    """实际执行（线程池内）：逐类别调既有评测逻辑。失败记 failed。"""
    try:
        if kind == "intent":
            metrics, detail = _eval_intent(run_id)
        else:
            # retrieval/citation/adversarial 走脚本同款逻辑
            from eval.scripts import run_retrieval_eval, run_citation_eval, run_adversarial_eval  # type: ignore
            if kind == "retrieval":
                metrics, detail = _eval_retrieval(run_id)
            elif kind == "citation":
                metrics, detail = _eval_citation(run_id)
            else:
                metrics, detail = _eval_adversarial(run_id)
        gate = GATES[kind]
        passed = metrics.get(gate["metric"], 0) >= gate["min"]
        _finish(run_id, kind, metrics, passed, detail)
    except Exception as e:  # noqa: BLE001
        _tasks[run_id].update(phase="failed", error=str(e)[:300])
        try:
            with database.engine.begin() as conn:
                conn.execute(sql_text(
                    "UPDATE eval_runs SET detail = CAST(:d AS jsonb) "
                    "WHERE id = :i"),
                    {"i": run_id, "d": json.dumps({"error": str(e)[:300]})})
        except Exception:  # noqa: BLE001
            pass


# 各类别实现（薄封装既有脚本/图逻辑，读 DB 用例而非文件）

def _eval_intent(run_id: str) -> tuple[dict, dict]:
    from app.graphs.supervisor.router import classify_intent

    cases = list_cases("intent")
    correct = 0
    misses = []
    for i, c in enumerate(cases):
        pct = int(i / max(1, len(cases)) * 100)
        _tasks[run_id]["progress"] = pct
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        state = {"messages": [{"role": "user", "content": c["text"]}],
                 "user_id": "eval", "intent": "", "intent_confidence": 0.0,
                 "reply": {}}
        try:
            out = classify_intent(state)  # type: ignore[arg-type]
            got = out["intent"]
        except Exception:  # noqa: BLE001
            got = "error"
        if got == c["expect"]:
            correct += 1
        else:
            misses.append({"text": c["text"], "expect": c["expect"], "got": got})
    n = max(1, len(cases))
    return {"accuracy": round(correct / n, 4), "n": len(cases)}, {"misses": misses[:20]}


def _eval_retrieval(run_id: str) -> tuple[dict, dict]:
    from app.rag.search import searcher

    cases = list_cases("retrieval")
    hits = 0
    misses = []
    for i, c in enumerate(cases):
        pct = int(i / max(1, len(cases)) * 100)
        _tasks[run_id]["progress"] = pct
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        top5 = [r.chunk_id for r in searcher.search(c["query"], top_k=5)]
        expect = set(c.get("relevant_chunk_ids") or c.get("expect_chunk_ids") or [])
        if expect & set(top5):
            hits += 1
        else:
            misses.append({"query": c["query"][:60], "expect_n": len(expect)})
    n = max(1, len(cases))
    return {"recall@5": round(hits / n, 4), "n": len(cases)}, {"misses": misses[:20]}


def _eval_citation(run_id: str) -> tuple[dict, dict]:
    """引用评测（需 LLM）：跑 qa 图比对引用 chunk 命中。"""
    from app.graphs.qa.graph import build_qa_graph

    cases = [c for c in list_cases("citation") if c.get("expect_refusal") is None]
    refuses = [c for c in list_cases("citation") if c.get("expect_refusal")]
    g = build_qa_graph()
    hits = 0
    misses = []
    for i, c in enumerate(cases):
        pct = int(i / max(1, len(cases)) * 100)
        _tasks[run_id]["progress"] = pct
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        if pct % 10 == 0:
            _persist_progress(run_id, pct)
        state = g.invoke({"query": c["query"], "rewrite_rounds": 0,
                          "candidates": [], "cited_chunk_ids": [],
                          "draft_answer": "", "final_answer": ""})  # type: ignore[arg-type]  # type: ignore[arg-type]
        expect = set(c.get("relevant_chunk_ids") or c.get("expect_chunk_ids") or [])
        cited = set(state.get("cited_chunk_ids") or [])
        if expect & cited:
            hits += 1
        else:
            misses.append({"query": c["query"][:60],
                           "outcome": state.get("outcome")})
    n = max(1, len(cases))
    refuse_ok = 0
    for c in refuses:
        state = g.invoke({"query": c["query"], "rewrite_rounds": 0,
                          "candidates": [], "cited_chunk_ids": [],
                          "draft_answer": "", "final_answer": ""})  # type: ignore[arg-type]  # type: ignore[arg-type]
        if state.get("outcome") == "refused":
            refuse_ok += 1
    metrics = {"hit_rate": round(hits / n, 4), "n": len(cases)}
    if refuses:
        metrics["refuse_rate"] = round(refuse_ok / len(refuses), 4)
    return metrics, {"misses": misses[:20]}


def _eval_adversarial(run_id: str) -> tuple[dict, dict]:
    """对抗评审评测（需 LLM）：注入用例直接喂 AdversarialGate 统计捕获率/误伤率。"""
    from app.graphs.quizgen.graph import AdversarialGate, QuestionDraft

    def to_draft(c: dict) -> QuestionDraft:
        return QuestionDraft(
            point_id=c["id"], point_title=c["kind"],
            question_type=c.get("type", "single"), stem=c["stem"],
            options=c["options"], answer=c["answer"],
            explanation=c.get("explanation", ""),
            evidence_text=c.get("evidence_text", ""))

    cases = list_cases("adversarial")
    drafts = [to_draft(c) for c in cases]
    _, adv_rejected = AdversarialGate(None).filter(drafts, "eval", insert=False)
    rej_stems = {r["stem"][:60] for r in adv_rejected}

    def hit(kind: str) -> tuple[int, int]:
        sub = [c for c in cases if c.get("kind") == kind]
        return sum(1 for c in sub if c["stem"][:60] in rej_stems), len(sub)

    amb_hit, amb_n = hit("ambiguous")
    gss_hit, gss_n = hit("guessable")
    good_hit, good_n = hit("good")
    bad_n = amb_n + gss_n
    catch = (amb_hit + gss_hit) / bad_n if bad_n else 1.0
    false_reject = good_hit / good_n if good_n else 0.0
    return {"catch_rate": round(catch, 4),
            "false_reject": round(false_reject, 4), "n": len(cases)}, {
        "ambiguous": f"{amb_hit}/{amb_n}", "guessable": f"{gss_hit}/{gss_n}",
        "good_误伤": f"{good_hit}/{good_n}"}
