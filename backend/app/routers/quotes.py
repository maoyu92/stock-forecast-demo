"""行情接口 —— 快照/分时/K线（含技术指标序列）"""
from fastapi import APIRouter, HTTPException, Query

from ..services import quotes

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/spot")
def spot(codes: str = Query(..., description="逗号分隔，如 sh600000,sz000001,sh000001")):
    """批量实时快照（腾讯主源 + 新浪备源，5 秒缓存）"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(400, "codes 不能为空")
    if len(code_list) > 100:
        raise HTTPException(400, "单次最多 100 个代码")
    return {"quotes": quotes.spot(code_list)}


@router.get("/intraday")
def intraday(code: str):
    """当日分时（5 分钟K聚合 + 均价线）"""
    try:
        return quotes.intraday(code)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分时获取失败: {e}")


@router.get("/kline")
def kline(code: str, period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
          bars: int = Query(250, ge=30, le=800)):
    """K线 + 技术指标序列（MA/MACD/KDJ/RSI/BOLL），个股走本地仓库"""
    try:
        return quotes.kline_full(code, period, bars)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"K线获取失败: {e}")
