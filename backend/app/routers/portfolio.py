"""组合策略组回测接口"""
import threading

from fastapi import APIRouter, HTTPException

from .. import db
from ..schemas import PortfolioBacktestRequest
from ..services import portfolio_backtest as pb
from ..services.strategy_groups import list_groups

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/groups")
def groups():
    """全部策略组定义"""
    return {"groups": list_groups()}


@router.post("/backtest")
def run(req: PortfolioBacktestRequest):
    """后台启动组合策略组回测"""
    if pb.state().get("running"):
        return {"started": False, "state": pb.state()}

    def _job():
        try:
            pb.run_backtest(
                months=req.months,
                group_ids=req.group_ids,
                mode=req.mode,
                initial_cash=req.initial_cash,
                max_positions=req.max_positions,
                max_exposure=req.max_exposure,
                fee_rate=req.fee_rate,
                stamp_tax_rate=req.stamp_tax_rate,
                slippage=req.slippage,
                market_timing_enabled=req.market_timing_enabled,
                market_breadth_threshold=req.market_breadth_threshold,
                board=req.board,
                exclude_st=req.exclude_st,
                limit=req.limit,
                save=req.save,
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("portfolio_backtest").exception("组合策略组回测失败: %s", e)

    threading.Thread(target=_job, daemon=True, name="portfolio-backtest").start()
    return {"started": True, "state": pb.state()}


@router.get("/status")
def status():
    return pb.state()


@router.get("/report")
def report():
    result = pb.load_report()
    if result is None:
        raise HTTPException(404, "尚无组合回测报告，请先运行回测")
    return result


@router.get("/runs")
def runs(limit: int = 50):
    return {"runs": db.list_portfolio_runs(limit)}


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    r = db.get_portfolio_run(run_id)
    if r is None:
        raise HTTPException(404, "回测记录不存在")
    return r
