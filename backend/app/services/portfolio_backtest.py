"""组合策略组回测 —— 完整持仓/卖出/成本模拟

与 `backtest.py` 的差异：
- backtest.py 是“信号日收盘买入，固定持有 1/3/5/10 日”的信号级体检；
- 本模块是真正的组合状态机，支持入场、止损、时间退出、成本、仓位与净值曲线。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, db
from . import histstore
from .screener import base as screener_base
from .screener.formula import engine
from .strategy_groups import indicators as ind
from .strategy_groups.base import StrategyGroupDef, get_group, list_groups

log = logging.getLogger("portfolio_backtest")

REPORT_PATH = Path(config.DATABASE_PATH).parent / "portfolio_backtest_report.json"

_state_lock = threading.Lock()
_state: dict = {
    "running": False, "phase": "", "done": 0, "total": 0,
    "started_at": None, "finished_at": None, "error": None,
}


def state() -> dict:
    with _state_lock:
        return dict(_state)


def load_report() -> dict | None:
    if not REPORT_PATH.exists():
        return None
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _set_state(**kw) -> None:
    with _state_lock:
        _state.update(kw)


# ---------- 数据结构 ----------

@dataclass
class Position:
    group_id: str
    stock_idx: int
    code: str
    name: str
    signal_date_idx: int
    entry_date_idx: int
    entry_price: float
    shares: int
    cost: float
    stop_price: float
    highest_close: float
    last_close: float = 0.0
    pending_exit: bool = False
    exit_reason: str = ""
    signal_date: str = ""
    entry_date: str = ""


@dataclass
class UniverseData:
    dates: list[str]
    codes: list[str]
    names: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    amount: np.ndarray
    atr20: np.ndarray
    prev_close: np.ndarray
    close_filled: np.ndarray
    above_ma60: np.ndarray
    entry: dict[str, np.ndarray]
    exit: dict[str, np.ndarray]
    market_breadth: np.ndarray
    market_ok: np.ndarray


# ---------- 公式与指标准备 ----------

def _formula_jobs(ids: set[str]) -> dict[str, tuple[object, dict]]:
    out: dict[str, tuple[object, dict]] = {}
    for sid in ids:
        try:
            st = screener_base.get_strategy(sid)
            params = {p.key: p.default for p in st.params}
            out[sid] = (engine.compile_formula(st.formula), params)
        except Exception as e:  # noqa: BLE001
            log.warning("策略公式 %s 编译失败: %s", sid, e)
    return out


def _combine_series(signals: list[pd.Series], combine: str) -> pd.Series:
    if not signals:
        return pd.Series(False, index=[])
    out = signals[0].copy()
    for s in signals[1:]:
        if combine == "and":
            out &= s
        else:
            out |= s
    return out.fillna(False).astype(bool)


def _fill_matrix(arr: np.ndarray, col: int, dates: list[str],
                 series: pd.Series | np.ndarray, date_to_idx: dict[str, int],
                 local_dates: list[str]) -> None:
    """把一只股票的按日序列写入全局矩阵的对应列"""
    vals = series.to_numpy() if isinstance(series, pd.Series) else np.asarray(series)
    for j, d in enumerate(local_dates):
        gi = date_to_idx.get(d)
        if gi is None or j >= len(vals):
            continue
        v = vals[j]
        if isinstance(v, (np.bool_, bool)):
            arr[gi, col] = bool(v)
        elif v is not None and not (isinstance(v, float) and np.isnan(v)):
            try:
                arr[gi, col] = float(v)
            except (TypeError, ValueError):
                continue


def _stock_signal_job(args):
    """单只股票：读K线、算指标、求各策略组信号。返回可直接写矩阵的结果"""
    col, code, name, bars, group_defs = args
    df = histstore.read_kline(code, bars)
    if len(df) < 80:
        return col, None
    local_dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

    close = df["close"].astype(float)
    atr20 = ind.atr(df, 20)
    ma60 = ind.ma(close, 60)
    prev_close = close.shift(1)
    above_ma60 = (close > ma60).fillna(False).astype(bool)

    needed_ids: set[str] = set()
    for g in group_defs:
        needed_ids.update(g.entry_ids)
        needed_ids.update(g.risk_ids)
    jobs = _formula_jobs(needed_ids)

    entry_arrays: dict[str, np.ndarray] = {}
    exit_arrays: dict[str, np.ndarray] = {}
    risk_block = None
    risk_ids = {sid for g in group_defs for sid in g.risk_ids}
    if risk_ids:
        risk_series = None
        for sid in risk_ids:
            if sid not in jobs:
                continue
            sig, _ = jobs[sid][0].eval(df, jobs[sid][1])
            risk_series = sig if risk_series is None else (risk_series | sig)
        if risk_series is not None:
            # 风险信号放宽到 2 日内出现过即阻塞新开仓
            risk_block = (risk_series.astype(float)
                          .rolling(2, min_periods=1).max().fillna(0) > 0)

    for g in group_defs:
        sigs: list[pd.Series] = []
        for sid in g.entry_ids:
            if sid not in jobs:
                continue
            sig, _ = jobs[sid][0].eval(df, jobs[sid][1])
            sigs.append(sig.fillna(False).astype(bool))
        entry = _combine_series(sigs, g.entry_combine)
        if risk_block is not None:
            entry &= ~risk_block
        if g.min_amount > 0:
            entry &= (df["amount"].fillna(0) >= g.min_amount * 1e8)
        entry &= (close > 0)
        entry_arrays[g.id] = entry.fillna(False).astype(bool)
        exit_arrays[g.id] = ind.exit_signal(df, g.exit_kind)

    return col, {
        "code": code, "name": name,
        "local_dates": local_dates,
        "open": df["open"].to_numpy(dtype=float),
        "high": df["high"].to_numpy(dtype=float),
        "low": df["low"].to_numpy(dtype=float),
        "close": close.to_numpy(dtype=float),
        "volume": df["volume"].to_numpy(dtype=float),
        "amount": df["amount"].to_numpy(dtype=float),
        "atr20": atr20.to_numpy(dtype=float),
        "prev_close": prev_close.to_numpy(dtype=float),
        "above_ma60": above_ma60.to_numpy(dtype=bool),
        "entry": {gid: s.to_numpy(dtype=bool) for gid, s in entry_arrays.items()},
        "exit": {gid: s.to_numpy(dtype=bool) for gid, s in exit_arrays.items()},
    }


def _load_universe(group_defs: list[StrategyGroupDef], months: float,
                   board: str, exclude_st: bool, limit: int | None) -> UniverseData:
    codes_df = histstore.all_codes()
    if codes_df.empty:
        raise RuntimeError("本地历史K线仓库为空，请先同步数据")
    codes_df = codes_df.copy()
    codes_df["code6"] = codes_df["code"].str.split(".").str[-1]
    if board == "主板":
        codes_df = codes_df[codes_df["code6"].str.startswith(("60", "00"))]
    elif board == "创业板":
        codes_df = codes_df[codes_df["code6"].str.startswith("30")]
    elif board == "科创板":
        codes_df = codes_df[codes_df["code6"].str.startswith("68")]
    if exclude_st:
        codes_df = codes_df[~codes_df["name"].str.upper().str.contains("ST", na=False)]
    if limit:
        codes_df = codes_df.head(int(limit))
    rows = list(codes_df[["code", "name"]].itertuples(index=False, name=None))
    if not rows:
        raise RuntimeError("过滤后没有可用股票")

    trading_days = max(20, int(months * 21))
    warmup = 80
    bars = min(trading_days + warmup + 10, 320)
    needed_dates = trading_days + warmup + 10

    _set_state(phase="准备信号矩阵", total=len(rows), done=0)
    args_list = [(i, code, name, bars, group_defs)
                 for i, (code, name) in enumerate(rows)]
    packed_results: list[tuple[int, dict | None]] = []
    date_set: set[str] = set()
    preview_step = max(1, len(rows) // 50)
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for col, packed in pool.map(_stock_signal_job, args_list):
            done += 1
            if col % preview_step == 0 or col == len(rows) - 1:
                _set_state(phase="准备信号矩阵", done=done, total=len(rows))
            if packed is None:
                continue
            packed_results.append((col, packed))
            date_set.update(packed["local_dates"])

    dates = sorted(date_set)
    if len(dates) > needed_dates:
        dates = dates[-needed_dates:]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_dates, n_stocks = len(dates), len(rows)

    open_m = np.full((n_dates, n_stocks), np.nan, dtype=np.float32)
    high_m = np.full_like(open_m, np.nan)
    low_m = np.full_like(open_m, np.nan)
    close_m = np.full_like(open_m, np.nan)
    volume_m = np.full_like(open_m, np.nan)
    amount_m = np.full_like(open_m, np.nan)
    atr_m = np.full_like(open_m, np.nan)
    prev_close_m = np.full_like(open_m, np.nan)
    above_ma60_m = np.zeros((n_dates, n_stocks), dtype=bool)
    entry_m = {g.id: np.zeros((n_dates, n_stocks), dtype=bool) for g in group_defs}
    exit_m = {g.id: np.zeros((n_dates, n_stocks), dtype=bool) for g in group_defs}

    for col, packed in packed_results:
        local_dates = packed["local_dates"]
        for j, d in enumerate(local_dates):
            gi = date_to_idx.get(d)
            if gi is None:
                continue
            for arr, key in [
                (open_m, "open"), (high_m, "high"), (low_m, "low"),
                (close_m, "close"), (volume_m, "volume"), (amount_m, "amount"),
                (atr_m, "atr20"), (prev_close_m, "prev_close"),
            ]:
                v = packed[key][j]
                if v is not None and not np.isnan(v):
                    arr[gi, col] = v
            above_ma60_m[gi, col] = bool(packed["above_ma60"][j])
            for gid, arr in entry_m.items():
                vals = packed["entry"].get(gid)
                if vals is not None:
                    arr[gi, col] = bool(vals[j])
            for gid, arr in exit_m.items():
                vals = packed["exit"].get(gid)
                if vals is not None:
                    arr[gi, col] = bool(vals[j])

    codes = [r[0] for r in rows]
    names = [r[1] for r in rows]
    close_filled = pd.DataFrame(close_m).ffill().to_numpy(dtype=np.float32)
    den = np.isfinite(close_m).sum(axis=1)
    breadth = np.divide(
        above_ma60_m.sum(axis=1), den,
        out=np.zeros(n_dates, dtype=float), where=den > 0,
    )
    return UniverseData(
        dates=dates, codes=codes, names=names,
        open=open_m, high=high_m, low=low_m, close=close_m,
        volume=volume_m, amount=amount_m,
        atr20=atr_m, prev_close=prev_close_m, close_filled=close_filled,
        above_ma60=above_ma60_m, entry=entry_m, exit=exit_m,
        market_breadth=breadth, market_ok=breadth >= 0.45,
    )


def _apply_forecast_mask(universe: UniverseData, group_ids: list[str]) -> int:
    """TimesFM 组：只信任非 mock 的历史预测记录，且信号只在预测生成后 5 个交易日内有效"""
    if "timesfm_enhanced" not in group_ids or "timesfm_enhanced" not in universe.entry:
        return 0
    records = db.list_history(limit=10000)
    code_to_idx = {c: i for i, c in enumerate(universe.codes)}
    date_index = pd.Index(universe.dates)
    forecast_mask = np.zeros_like(universe.entry["timesfm_enhanced"], dtype=bool)
    used = 0
    for r in records:
        if r.get("inference_mode") == "mock":
            continue
        code = r.get("stock_code")
        if code not in code_to_idx:
            continue
        metrics = r.get("metrics") or {}
        if not metrics.get("predicted_change_pct") or metrics["predicted_change_pct"] < 3:
            continue
        if not metrics.get("forecast_mean") or not metrics.get("last_value"):
            continue
        if metrics["forecast_mean"] <= metrics["last_value"]:
            continue
        created = str(r.get("created_at") or "")[:10]
        if not created:
            continue
        si = code_to_idx[code]
        start = date_index.searchsorted(created)
        if start >= len(universe.dates):
            continue
        used += 1
        for k in range(start, min(start + 5, len(universe.dates))):
            forecast_mask[k, si] = True
    universe.entry["timesfm_enhanced"] &= forecast_mask
    return used


# ---------- 回测核心 ----------

def _current_stop_price(pos: Position, atr_value: float, g: StrategyGroupDef) -> float:
    floor_price = pos.entry_price * (1 - g.hard_stop_pct)
    if not pos.highest_close or pos.highest_close <= 0:
        return floor_price
    candidates = [floor_price, pos.highest_close * (1 - g.trail_drawdown_pct)]
    if atr_value and not np.isnan(atr_value) and atr_value > 0:
        candidates.append(pos.highest_close - atr_value * g.stop_atr_mult)
    return max(candidates)


def _metrics(curve: list[dict], trades: list[dict], initial_cash: float) -> dict:
    if not curve:
        return {}
    equity = np.array([x["equity"] for x in curve], dtype=float)
    final_equity = float(equity[-1])
    total_return = final_equity / initial_cash - 1
    days = max(0, len(equity) - 1)
    annualized = (1 + total_return) ** (252 / days) - 1 if days > 0 and final_equity > 0 else 0
    rolling_max = np.maximum.accumulate(equity)
    drawdown = equity / rolling_max - 1
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0
    daily_ret = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([])
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) \
        if len(daily_ret) > 1 and daily_ret.std() > 0 else 0
    returns = [float(t["return_pct"]) for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 \
        else (99.0 if wins else 0.0)
    holding_days = [int(t["holding_days"]) for t in trades]
    return {
        "start_date": curve[0]["date"],
        "end_date": curve[-1]["date"],
        "days": days,
        "initial_cash": initial_cash,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(annualized * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "sharpe": round(sharpe, 2),
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 2) if returns else 0,
        "avg_trade_return_pct": round(float(np.mean(returns)), 2) if returns else 0,
        "median_trade_return_pct": round(float(np.median(returns)), 2) if returns else 0,
        "profit_factor": round(profit_factor, 2),
        "avg_holding_days": round(float(np.mean(holding_days)), 1) if holding_days else 0,
        "total_fees": round(float(sum(t["fees"] for t in trades)), 2),
        "turnover_pct": round(float(sum(t["buy_amount"] for t in trades) / initial_cash * 100), 2),
        "max_exposure_pct": round(max(x["exposure_pct"] for x in curve), 2),
        "avg_exposure_pct": round(float(np.mean([x["exposure_pct"] for x in curve])), 2),
    }


def _group_summary(group_ids: list[str], trades: list[dict]) -> list[dict]:
    out = []
    for gid in group_ids:
        ts = [t for t in trades if t["group_id"] == gid]
        rets = [t["return_pct"] for t in ts]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        out.append({
            "group_id": gid,
            "trades": len(ts),
            "win_rate_pct": round(len(wins) / len(rets) * 100, 2) if rets else 0,
            "avg_return_pct": round(float(np.mean(rets)), 2) if rets else 0,
            "realized_pnl": round(float(sum(t["pnl"] for t in ts)), 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2)
            if losses and sum(losses) != 0 else (99.0 if wins else 0.0),
        })
    return out


def _simulate(universe: UniverseData, groups: list[StrategyGroupDef],
              params: dict) -> dict:
    initial_cash = float(params["initial_cash"])
    cash = initial_cash
    positions: dict[tuple[str, int], Position] = {}
    trades: list[dict] = []
    curve: list[dict] = []
    start_idx = max(1, len(universe.dates) - int(params["months"] * 21) - 1)
    fee_rate = float(params["fee_rate"])
    stamp_tax = float(params["stamp_tax_rate"])
    slippage = float(params["slippage"])
    total_max_positions = int(params["max_positions"])
    max_exposure = float(params["max_exposure"])
    market_timing = bool(params["market_timing_enabled"])

    def group_pos_count(gid: str) -> int:
        return sum(1 for p in positions.values() if p.group_id == gid)

    for t in range(start_idx, len(universe.dates)):
        # 1) 开盘处理昨日技术退出 / 时间退出 / 追踪止损
        for key, pos in list(positions.items()):
            si = pos.stock_idx
            o = float(universe.open[t, si])
            h = float(universe.high[t, si])
            l = float(universe.low[t, si])
            pc = float(universe.prev_close[t, si])
            if not np.isfinite(o) or not np.isfinite(pc) or o <= 0:
                continue
            if t <= pos.entry_date_idx:
                continue
            g = get_group(pos.group_id)
            exit_reason = ""
            if pos.pending_exit:
                exit_reason = pos.exit_reason or "signal_exit"
            elif universe.exit[pos.group_id][t - 1, si]:
                exit_reason = "technical_exit"
            if exit_reason:
                if ind.is_limit_down(o, pc, pos.code):
                    continue
                exec_price = o
                cash += _sell_position(positions, trades, key, pos, t, exec_price,
                                       exit_reason, fee_rate, stamp_tax, slippage,
                                       universe.dates)
                continue
            atr = float(universe.atr20[t - 1, si])
            stop = _current_stop_price(pos, atr, g)
            if np.isfinite(l) and l <= stop:
                if ind.is_limit_down(o, pc, pos.code):
                    continue
                exec_price = min(o, stop)
                cash += _sell_position(positions, trades, key, pos, t, exec_price,
                                       "stop_loss", fee_rate, stamp_tax, slippage,
                                       universe.dates)

        # 2) 开盘买入
        prev_equity = curve[-1]["equity"] if curve else initial_cash
        market_ok = (not market_timing) or bool(universe.market_ok[t - 1])
        current_market_value = sum(
            pos.shares * float(universe.close_filled[t - 1, pos.stock_idx])
            for pos in positions.values()
        )
        current_exposure = current_market_value / prev_equity if prev_equity > 0 else 0
        if market_ok and len(positions) < total_max_positions and current_exposure < max_exposure:
            candidates: list[tuple[str, int, float]] = []
            for g in groups:
                if group_pos_count(g.id) >= g.max_positions:
                    continue
                entry_mat = universe.entry[g.id]
                if t - 1 < 0:
                    continue
                idxs = np.flatnonzero(entry_mat[t - 1])
                for si in idxs:
                    if (g.id, int(si)) in positions:
                        continue
                    o = float(universe.open[t, si])
                    pc = float(universe.prev_close[t, si])
                    amt = float(universe.amount[t - 1, si])
                    if not np.isfinite(o) or not np.isfinite(pc) or o <= 0:
                        continue
                    if ind.is_limit_up(o, pc, universe.codes[si]):
                        continue
                    if amt < g.min_amount * 1e8:
                        continue
                    candidates.append((g.id, int(si), amt))
            candidates.sort(key=lambda x: -x[2])
            for gid, si, _amt in candidates:
                if len(positions) >= total_max_positions:
                    break
                if group_pos_count(gid) >= get_group(gid).max_positions:
                    continue
                g = get_group(gid)
                o = float(universe.open[t, si])
                pc = float(universe.prev_close[t, si])
                if ind.is_limit_up(o, pc, universe.codes[si]):
                    continue
                exec_price = o * (1 + slippage)
                atr = float(universe.atr20[t - 1, si])
                if not np.isfinite(atr) or atr <= 0:
                    atr = exec_price * g.hard_stop_pct / max(g.stop_atr_mult, 0.1)
                stop_distance = max(exec_price * g.hard_stop_pct, atr * g.stop_atr_mult)
                shares_by_weight = prev_equity * g.max_weight / exec_price
                shares_by_risk = prev_equity * g.risk_per_trade / stop_distance
                shares = int(min(shares_by_weight, shares_by_risk) // 100 * 100)
                # 现金约束
                while shares > 0:
                    buy_amount = shares * exec_price
                    fee = max(5.0, buy_amount * fee_rate)
                    if buy_amount + fee <= cash:
                        break
                    shares -= 100
                if shares <= 0:
                    continue
                buy_amount = shares * exec_price
                fee = max(5.0, buy_amount * fee_rate)
                if buy_amount + fee > cash:
                    continue
                projected_value = current_market_value + buy_amount
                if prev_equity > 0 and projected_value / prev_equity > max_exposure:
                    continue
                cash -= buy_amount + fee
                stop_price = exec_price - stop_distance
                positions[(gid, si)] = Position(
                    group_id=gid, stock_idx=si, code=universe.codes[si],
                    name=universe.names[si], signal_date_idx=t - 1,
                    entry_date_idx=t, entry_price=exec_price, shares=shares,
                    cost=buy_amount + fee, stop_price=stop_price,
                    highest_close=exec_price,
                    signal_date=universe.dates[t - 1],
                    entry_date=universe.dates[t],
                )

        # 3) 收盘后更新持仓 / 记录净值 / 标记时间退出
        for key, pos in list(positions.items()):
            si = pos.stock_idx
            close = float(universe.close[t, si])
            if np.isfinite(close) and close > 0:
                pos.last_close = close
                pos.highest_close = max(pos.highest_close, close)
            if t > pos.entry_date_idx and universe.exit[pos.group_id][t, si]:
                pos.pending_exit = True
                pos.exit_reason = pos.exit_reason or "technical_exit"
            holding_days = t - pos.entry_date_idx
            if holding_days >= get_group(pos.group_id).max_holding_days:
                ret = (pos.last_close / pos.entry_price - 1) if pos.last_close else 0
                if ret < get_group(pos.group_id).time_exit_min_return_pct:
                    pos.pending_exit = True
                    pos.exit_reason = pos.exit_reason or "time_exit"

        market_value = 0.0
        for pos in positions.values():
            price = float(universe.close_filled[t, pos.stock_idx])
            if not np.isfinite(price) or price <= 0:
                price = pos.entry_price
            market_value += pos.shares * price
        equity = cash + market_value
        exposure = market_value / equity if equity > 0 else 0
        curve.append({
            "date": universe.dates[t],
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "exposure_pct": round(exposure * 100, 2),
            "positions": len(positions),
        })

    # 回测结束强平剩余仓位，便于统计完整盈亏
    last_t = len(universe.dates) - 1
    for key, pos in list(positions.items()):
        price = float(universe.close_filled[last_t, pos.stock_idx])
        if not np.isfinite(price) or price <= 0:
            price = pos.entry_price
        cash += _sell_position(positions, trades, key, pos, last_t, price,
                               "backtest_end", fee_rate, stamp_tax, slippage,
                               universe.dates)

    group_ids = [g.id for g in groups]
    metrics = _metrics(curve, trades, initial_cash)
    metrics["group_summary"] = _group_summary(group_ids, trades)
    return {
        "group_ids": group_ids,
        "metrics": metrics,
        "equity_curve": curve,
        "trades": trades,
    }


def _sell_position(positions: dict, trades: list[dict], key, pos: Position,
                   t: int, exec_price: float, reason: str,
                   fee_rate: float, stamp_tax: float, slippage: float,
                   dates: list[str]) -> float:
    net_price = exec_price * (1 - slippage)
    proceeds = pos.shares * net_price
    fee = max(5.0, proceeds * fee_rate) + proceeds * stamp_tax
    buy_fee = max(0.0, pos.cost - pos.shares * pos.entry_price)
    pnl = proceeds - fee - pos.cost
    return_pct = pnl / pos.cost if pos.cost else 0
    positions.pop(key, None)
    trades.append({
        "group_id": pos.group_id,
        "code": pos.code,
        "name": pos.name,
        "signal_date": pos.signal_date,
        "entry_date": pos.entry_date,
        "exit_date": dates[t] if 0 <= t < len(dates) else "",
        "entry_price": round(pos.entry_price, 4),
        "exit_price": round(net_price, 4),
        "shares": pos.shares,
        "buy_amount": round(pos.cost, 2),
        "sell_amount": round(proceeds, 2),
        "fees": round(buy_fee + fee, 2),
        "pnl": round(pnl, 2),
        "return_pct": round(return_pct * 100, 2),
        "holding_days": max(1, t - pos.entry_date_idx),
        "exit_reason": reason,
    })
    return proceeds - fee


# ---------- 对外入口 ----------

def run_backtest(
    months: float = 12,
    group_ids: list[str] | None = None,
    mode: str = "both",
    initial_cash: float = 1_000_000,
    max_positions: int = 8,
    max_exposure: float = 0.95,
    fee_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage: float = 0.001,
    market_timing_enabled: bool = True,
    market_breadth_threshold: float = 0.45,
    board: str = "全部",
    exclude_st: bool = True,
    limit: int | None = None,
    save: bool = True,
) -> dict:
    """运行组合策略组回测。耗时视数据量而定，几百只约数十秒，全市场可能数分钟。"""
    with _state_lock:
        if _state["running"]:
            return {"running": True, "state": dict(_state)}
        _state.update(running=True, phase="启动", done=0, total=0,
                      started_at=datetime.now().isoformat(timespec="seconds"),
                      finished_at=None, error=None)
    t0 = time.time()
    try:
        all_defs = list_groups()
        if not group_ids:
            group_ids = [g["id"] for g in all_defs if g["enabled"]]
        unknown = [gid for gid in group_ids if gid not in {g["id"] for g in all_defs}]
        if unknown:
            raise ValueError(f"未知策略组: {unknown}")
        defs = [get_group(gid) for gid in group_ids]
        if not defs:
            raise ValueError("未选择策略组")
        universe = _load_universe(defs, months, board, exclude_st, limit)
        used_forecasts = _apply_forecast_mask(universe, group_ids)
        universe.market_ok = universe.market_breadth >= market_breadth_threshold
        params = {
            "months": months, "mode": mode, "initial_cash": initial_cash,
            "max_positions": max_positions, "max_exposure": max_exposure,
            "fee_rate": fee_rate, "stamp_tax_rate": stamp_tax_rate,
            "slippage": slippage, "market_timing_enabled": market_timing_enabled,
            "market_breadth_threshold": market_breadth_threshold,
            "board": board, "exclude_st": exclude_st, "limit": limit,
        }
        warnings = []
        if "timesfm_enhanced" in group_ids and used_forecasts == 0:
            warnings.append("TimesFM 组未找到可用的非 mock 历史预测记录，本组不会产生交易。")

        runs: list[dict] = []
        if mode in ("individual", "both"):
            for g in defs:
                _set_state(phase=f"回测 {g.name}")
                run = _simulate(universe, [g], params)
                run["group_name"] = g.name
                run["mode"] = "individual"
                runs.append(run)
        if mode in ("combined", "both"):
            _set_state(phase="回测组合")
            run = _simulate(universe, defs, params)
            run["group_name"] = "全组合"
            run["mode"] = "combined"
            runs.append(run)

        result = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_as_of": histstore.status().get("data_as_of"),
            "universe_size": len(universe.codes),
            "start_date": universe.dates[0],
            "end_date": universe.dates[-1],
            "params": params,
            "group_ids": group_ids,
            "warnings": warnings,
            "runs": runs,
            "elapsed_s": round(time.time() - t0, 1),
            "disclaimer": "历史回测仅供研究，不构成投资建议。",
        }
        if save:
            REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            db.save_portfolio_run(params, result, round(time.time() - t0, 1))
        _set_state(phase="完成", running=False,
                   finished_at=datetime.now().isoformat(timespec="seconds"))
        return result
    except Exception as e:  # noqa: BLE001
        log.exception("组合策略组回测失败")
        _set_state(phase=f"失败: {e}", running=False,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   error=str(e))
        raise
