"""设置端点：可编辑项列表 / 保存（校验失败 400）/ 重置。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import settings_service as ss

router = APIRouter()


@router.get("/settings")
def list_settings() -> dict:
    return {"settings": ss.list_settings()}


class UpdateReq(BaseModel):
    value: object


@router.put("/settings/{key}")
def update_setting(key: str, req: UpdateReq) -> dict:
    try:
        return ss.update_setting(key, req.value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/settings/{key}")
def reset_setting(key: str) -> dict:
    try:
        return ss.reset_setting(key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
