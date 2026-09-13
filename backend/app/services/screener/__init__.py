"""智能选股服务 —— 编排入口

流程：策略注册表（base）→ 东财全市场快照（emdata）→ 第一层快筛
→ 逐只拉日K（复用 datasource.fetch_kline）→ 第二层因子打分 → 排序落库。

新增选股方法：在本包新建模块，定义 StrategyDef 并 register()，
然后在下方 import 触发注册。模块需约定实现：
  STRATEGY_ID: str
  prefilter(snapshot_df, params) -> (候选DataFrame, 快筛前股票数)
  score_stock(kline_df, snapshot_row, params, kline_includes_today) -> 结果dict | None
"""
import importlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .. import datasource
from . import base, emdata, moneyrank, moneytree, smartmoney  # noqa: F401 —— import 触发策略注册
from .base import get_strategy, get_param, list_strategies
from .formula import catalog as formula_catalog  # noqa: F401 —— 注册公式策略

log = logging.getLogger("screener")

# 公式策略在 catalog 模块内注册（import 时编译验证全部公式）
formula_catalog.register_all()

# 进程内互斥：同一时间只允许一个选股任务（保护 baostock 单连接与限流）
RUN_LOCK = threading.Lock()

# K 线数据允许的最大滞后天数（超过视为长期停牌，跳过）
_KLINE_STALE_DAYS = 7


def _strategy_module(strategy_id: str):
    return importlib.import_module(f".{strategy_id}", __package__)


def _analyze_one(mod, row: dict, p: dict, start: str) -> dict | None:
    """单只股票深度分析：拉K线 → 打分。失败/硬条件不过返回 None。"""
    code = emdata.to_bs_code(row["code6"])
    try:
        kline = datasource.fetch_kline(code, period="daily", start=start)
    except Exception as e:  # noqa: BLE001 —— 单只失败不阻断
        log.warning("选股拉K线失败 %s: %s", code, e)
        return None
    if kline.empty or len(kline) < 80:  # 次新股/数据不足，指标不可信
        return None
    lag = (datetime.now() - kline["date"].iloc[-1].to_pydatetime()).days
    if lag > _KLINE_STALE_DAYS:  # 长期停牌
        return None
    try:
        return mod.score_stock(kline, row, p)
    except Exception as e:  # noqa: BLE001
        log.warning("选股打分失败 %s: %s", code, e)
        return None


def _run_strategy(st: base.StrategyDef, p: dict) -> tuple[list[dict], dict]:
    """两段式编排：mod.prefilter(snap) → 并发逐只深度分析（K线在 baostock
    进程锁内串行获取，资金流等网络请求与打分并行重叠，缩短总耗时）"""
    if st.kind == "formula":
        from .formula import runner
        return runner.run_formula_strategy(st, p)

    mod = _strategy_module(st.id)
    snap, snap_time = emdata.get_snapshot()
    candidates, total = mod.prefilter(snap, p)
    start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    rows = candidates.to_dict("records")

    with ThreadPoolExecutor(max_workers=6) as pool:
        entries = list(pool.map(lambda r: _analyze_one(mod, r, p, start), rows))
    results = [e for e in entries if e is not None]

    results.sort(key=lambda r: -r["score"])
    for i, r in enumerate(results, 1):
        r["rank"] = i
    meta = {"snapshot_time": snap_time, "total_screened": int(total),
            "candidates": int(len(candidates))}
    return results, meta


def run_screen(strategy_id: str, params: dict | None = None, save: bool = True) -> dict:
    """执行一次选股。返回含结果与元信息的 dict（save=True 时附带 run_id 并落库）。"""
    from ... import db

    st = get_strategy(strategy_id)
    params = params or {}
    merged = {p.key: get_param(params, p) for p in st.params}

    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("已有选股任务在运行中，请稍候再试")
    t0 = time.time()
    try:
        results, meta = _run_strategy(st, merged)
    finally:
        RUN_LOCK.release()

    elapsed_ms = int((time.time() - t0) * 1000)
    payload = {
        "strategy_id": st.id,
        "strategy_name": st.name,
        "params": merged,
        "snapshot_time": meta["snapshot_time"],
        "total_screened": meta["total_screened"],
        "candidates": meta["candidates"],
        "elapsed_ms": elapsed_ms,
        "result_count": len(results),
        "results": results,
        "disclaimer": "选股结果由历史数据量化规则生成，仅供研究参考，不构成投资建议。",
    }
    if save:
        try:
            payload["run_id"] = db.save_screen_run(
                strategy_id=st.id, strategy_name=st.name, params=merged,
                snapshot_time=meta["snapshot_time"], total_screened=meta["total_screened"],
                elapsed_ms=elapsed_ms, results=results)
        except Exception as e:  # noqa: BLE001 —— 落库失败不影响返回
            log.warning("选股结果落库失败: %s", e)
    return payload


def _merge_common(st: base.StrategyDef, common: dict) -> dict:
    """组合模式：公共参数覆盖（within_n/board/exclude_st/min_amount 等），
    其余专属参数用各策略默认值"""
    out = {}
    for p in st.params:
        if p.key in common:
            out[p.key] = get_param({p.key: common[p.key]}, p)
        else:
            out[p.key] = get_param({}, p)
    return out


def run_screen_multi(strategy_ids: list[str], combine: str = "or",
                     exclude_ids: list[str] | None = None,
                     params: dict | None = None, save: bool = True) -> dict:
    """多策略组合选股：单次扫描评估全部公式后做集合运算（and=交集 / or=并集）。

    exclude_ids 为排除集（差集）：命中排除策略的股票从结果中剔除。
    仅支持公式策略（实时快照策略数据口径不同，不参与组合）。
    """
    from ... import db
    from .formula import runner

    defs = [get_strategy(s) for s in strategy_ids]
    bad = [d.name for d in defs if d.kind != "formula"]
    if bad:
        raise ValueError(f"组合选股仅支持公式策略，以下为实时快照策略不可加入: {'、'.join(bad)}")
    if len(defs) < 2 and combine == "and":
        raise ValueError("交集至少需要选择 2 个策略")

    seen = set(strategy_ids)
    excl_defs = []
    for sid in (exclude_ids or []):
        if sid in seen:
            continue  # 排除与已选重复时忽略
        d = get_strategy(sid)
        if d.kind != "formula":
            raise ValueError(f"排除策略仅支持公式策略: {d.name}")
        excl_defs.append(d)

    common = params or {}
    params_by_sid = {st.id: _merge_common(st, common) for st in defs}
    excl_params = {st.id: _merge_common(st, common) for st in excl_defs}

    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("已有选股任务在运行中，请稍候再试")
    t0 = time.time()
    try:
        results, meta = runner.run_multi_strategy(defs, params_by_sid, excl_defs,
                                                  excl_params, combine)
    finally:
        RUN_LOCK.release()

    elapsed_ms = int((time.time() - t0) * 1000)
    op = "交集" if combine == "and" else "并集"
    name = f"多策略{op}·{len(defs)}个"
    if excl_defs:
        name += f"(排除{len(excl_defs)}个)"
    payload = {
        "strategy_id": "__multi__",
        "strategy_name": name,
        "params": {"combine": combine, "strategy_ids": strategy_ids,
                   "exclude_ids": exclude_ids or [], **common},
        "snapshot_time": meta["snapshot_time"],
        "total_screened": meta["total_screened"],
        "candidates": meta["candidates"],
        "per_strategy": meta["per_strategy"],
        "excluded": meta["excluded"],
        "elapsed_ms": elapsed_ms,
        "result_count": len(results),
        "results": results,
        "disclaimer": "选股结果由历史数据量化规则生成，仅供研究参考，不构成投资建议。",
    }
    if save:
        try:
            payload["run_id"] = db.save_screen_run(
                strategy_id="__multi__", strategy_name=name, params=payload["params"],
                snapshot_time=meta["snapshot_time"], total_screened=meta["total_screened"],
                elapsed_ms=elapsed_ms, results=results)
        except Exception as e:  # noqa: BLE001
            log.warning("选股结果落库失败: %s", e)
    return payload
