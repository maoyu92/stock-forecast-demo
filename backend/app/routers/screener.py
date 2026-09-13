"""智能选股接口"""
from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..schemas import ScreenMultiRunRequest, ScreenRunRequest
from ..services import screener
from ..services.screener import base

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.get("/strategies")
def strategies():
    """选股方法列表 + 参数 schema（前端据此动态渲染表单）"""
    return {"strategies": base.list_strategies()}


@router.post("/run")
def run(body: ScreenRunRequest):
    """执行选股（同步接口，约 10~60 秒；同一时间仅允许一个任务）"""
    try:
        return screener.run_screen(body.strategy_id, body.params, body.save)
    except ValueError as e:  # 未知策略 id 等
        raise HTTPException(400, str(e))
    except RuntimeError as e:  # 并发限制 / 数据源不可用
        raise HTTPException(502, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"选股执行失败: {e}")


@router.post("/run-multi")
def run_multi(body: ScreenMultiRunRequest):
    """多策略组合选股：单次扫描评估全部公式后做交集/并集，支持排除集。

    仅支持公式策略；同一时间仅允许一个选股任务。
    """
    try:
        return screener.run_screen_multi(body.strategy_ids, body.combine,
                                         body.exclude_ids, body.params, body.save)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"组合选股执行失败: {e}")


@router.get("/runs")
def runs(limit: int = Query(50, ge=1, le=200)):
    return {"runs": db.list_screen_runs(limit)}


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    rec = db.get_screen_run(run_id)
    if not rec:
        raise HTTPException(404, f"选股记录不存在: {run_id}")
    return rec


@router.delete("/runs/{run_id}")
def delete_run(run_id: int):
    if not db.delete_screen_run(run_id):
        raise HTTPException(404, f"选股记录不存在: {run_id}")
    return {"ok": True}
