"""历史数据仓库接口 —— 通达信式"下载数据 → 本地选股" """
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import histstore

router = APIRouter(prefix="/api/data", tags=["data"])


class SyncRequest(BaseModel):
    years: float = Field(2.0, ge=1, le=8, description="全量模式下的历史年限")
    mode: str = Field("update", description="update=增量更新 / full=整窗重下")
    codes: list[str] = Field(default_factory=list, description="指定股票代码（空=全市场）")


@router.get("/status")
def data_status():
    """本地K线仓库状态（覆盖股票数/数据截至日/同步进度）"""
    return histstore.status()


@router.post("/sync")
def start_sync(body: SyncRequest):
    """启动历史数据同步（后台任务，进度轮询 GET /api/data/status）"""
    if body.mode not in ("update", "full"):
        raise HTTPException(400, f"不支持的同步模式: {body.mode}")
    try:
        st = histstore.sync(years=body.years, mode=body.mode, codes=body.codes or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"同步启动失败: {e}")
    return st
