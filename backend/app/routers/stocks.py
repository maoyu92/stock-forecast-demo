"""股票与行情接口"""
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from .. import config
from ..services import datasource

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 15):
    return {"results": datasource.search_stocks(q, limit)}


@router.get("/hot")
def hot():
    return {"results": datasource.HOT_STOCKS}


@router.get("/kline")
def kline(
    code: str = Query(..., description="如 sh.601601"),
    period: str = Query("daily"),
    days: int = Query(365, ge=30, le=3650, description="回看自然日数"),
):
    if period not in config.PERIODS:
        raise HTTPException(400, f"不支持的周期: {period}")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = datasource.fetch_kline(code, period=period, start=start)
    except Exception as e:
        raise HTTPException(502, f"行情获取失败: {e}")
    if df.empty:
        raise HTTPException(404, "未获取到行情数据，请检查代码或稍后重试")
    return {
        "code": code,
        "period": period,
        "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        "open": [None if pd_isna(v) else round(float(v), 4) for v in df["open"]],
        "high": [None if pd_isna(v) else round(float(v), 4) for v in df["high"]],
        "low": [None if pd_isna(v) else round(float(v), 4) for v in df["low"]],
        "close": [None if pd_isna(v) else round(float(v), 4) for v in df["close"]],
        "volume": [None if pd_isna(v) else float(v) for v in df["volume"]],
    }


def pd_isna(v) -> bool:
    return v is None or v != v
