"""评测端点：四类别触发/状态/用例管理（含 jsonl 批量导入导出）/历史。"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import eval_service as es

router = APIRouter()


@router.get("/eval/overview")
def overview() -> dict:
    es.init_eval_tables()
    counts = {k: len(es.list_cases(k)) for k in es.KINDS}
    return {"kinds": [
        {"kind": k, "cases": counts[k], "gate": es.GATES[k],
         "latest": next((r for r in es.latest_runs() if r["kind"] == k), None)}
        for k in es.KINDS]}


@router.post("/eval/{kind}/run")
def run(kind: str) -> dict:
    try:
        return {"run_id": es.run_eval(kind)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/eval/runs/{run_id}")
def task_status(run_id: str) -> dict:
    t = es.get_task(run_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在或已重启")
    return t


@router.get("/eval/{kind}/cases")
def cases(kind: str) -> dict:
    if kind not in es.KINDS:
        raise HTTPException(status_code=404, detail=f"未知类别：{kind}")
    es.init_eval_tables()
    return {"cases": es.list_cases(kind)}


class CaseReq(BaseModel):
    case: dict


@router.put("/eval/{kind}/cases")
def upsert(kind: str, req: CaseReq) -> dict:
    if kind not in es.KINDS:
        raise HTTPException(status_code=404, detail=f"未知类别：{kind}")
    return es.upsert_case(kind, req.case)


class ImportReq(BaseModel):
    jsonl: str  # jsonl 文本（一行一个用例 JSON）


@router.post("/eval/{kind}/import")
def import_jsonl(kind: str, req: ImportReq) -> dict:
    """批量导入用例：粘贴或上传的 jsonl 文本。逐行解析，非法行报行号。"""
    if kind not in es.KINDS:
        raise HTTPException(status_code=404, detail=f"未知类别：{kind}")
    es.init_eval_tables()
    ok, errors = 0, []
    for ln, line in enumerate(req.jsonl.splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            if not isinstance(case, dict):
                raise ValueError("用例须为 JSON 对象")
            es.upsert_case(kind, case)
            ok += 1
        except (ValueError, KeyError) as e:
            errors.append(f"第 {ln} 行：{e}")
    return {"imported": ok, "errors": errors[:10]}


@router.get("/eval/{kind}/export")
def export_jsonl(kind: str) -> dict:
    """导出当前用例为 jsonl 文本（备份/迁移）。"""
    if kind not in es.KINDS:
        raise HTTPException(status_code=404, detail=f"未知类别：{kind}")
    lines = "\n".join(
        json.dumps({k: v for k, v in c.items() if k != "enabled"},
                   ensure_ascii=False) for c in es.list_cases(kind))
    return {"jsonl": lines}


@router.delete("/eval/cases/{case_id}")
def remove(case_id: str) -> dict:
    return es.delete_case(case_id)


@router.get("/eval/{kind}/history")
def history(kind: str) -> dict:
    return {"runs": es.run_history(kind)}
