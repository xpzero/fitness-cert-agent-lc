"""评测端点：四类别触发/状态/用例管理/历史。"""

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


@router.delete("/eval/cases/{case_id}")
def remove(case_id: str) -> dict:
    return es.delete_case(case_id)


@router.get("/eval/{kind}/history")
def history(kind: str) -> dict:
    return {"runs": es.run_history(kind)}
