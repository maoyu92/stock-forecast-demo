"""策略回测接口 —— 报告查看 / 触发重跑"""
import threading

from fastapi import APIRouter, HTTPException

from ..services import backtest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/report")
def report():
    """最近一次回测报告（无报告返回 404）"""
    r = backtest.load_report()
    if r is None:
        raise HTTPException(404, "尚无回测报告，请先运行回测（POST /api/backtest/run 或 scripts/backtest.py）")
    return r


@router.get("/status")
def status():
    return backtest.backtest_state()


@router.post("/run")
def run(months: float = 12, min_signals: int = 100):
    """后台启动回测（约 5~15 分钟），进度轮询 /status，完成后 /report"""
    def _job():
        try:
            backtest.run_backtest(months=months, min_signals=min_signals)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("backtest").exception("回测失败: %s", e)

    st = backtest.backtest_state()
    if st.get("running"):
        return {"started": False, "state": st}
    threading.Thread(target=_job, daemon=True, name="backtest").start()
    return {"started": True, "state": backtest.backtest_state()}
