"""预测历史接口"""
from fastapi import APIRouter, HTTPException, Query

from .. import db

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def history(limit: int = Query(50, ge=1, le=500), code: str | None = None):
    return {"records": db.list_history(limit, code), "stats": db.history_stats()}


@router.get("/{record_id}")
def detail(record_id: int):
    rec = db.get_history(record_id)
    if rec is None:
        raise HTTPException(404, "记录不存在")
    return rec


@router.delete("/{record_id}")
def delete(record_id: int):
    if not db.delete_history(record_id):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}
