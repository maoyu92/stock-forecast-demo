"""策略历史回测 —— 信号胜率统计（选股公式的"体检报告"）

方法：
- 对每个公式策略，在全市场每只股票的近 ~250 根日K上求值出**全部历史信号**（非仅最后一根）；
- 每个信号按信号日收盘价入场，统计其后 1/3/5/10 个交易日的收盘收益；
- 信号产生后不足 max(horizons) 根K线的（结果未知）剔除，避免前视偏差；
- 指标：信号数、1/3/5/10 日胜率、5日平均/中位收益、5日盈亏比( avg_win/|avg_loss| )；
- 综合分 = 5日胜率×50% + 归一化5日均收益×30% + 归一化盈亏比×20%，样本不足（<min_signals）不参与排名。

口径说明：收盘→收盘，无滑点/手续费；前复权数据。排名用于筛选"确定性高"的策略组合，
胜率高≠未来胜率高，样本期约 1 年，仅供参考。
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config
from . import histstore
from .screener import base
from .screener.formula import engine

log = logging.getLogger("backtest")

REPORT_PATH = Path(config.DATABASE_PATH).parent / "backtest_report.json"
_HORIZONS = (1, 3, 5, 10)
_BARS = 320            # 与选股扫描一致
_MIN_STOCK_BARS = 120  # 股票数据不足则跳过
_WORKERS = 8

_state_lock = threading.Lock()
_state: dict = {"running": False, "done": 0, "total": 0, "started_at": None, "finished_at": None}


def backtest_state() -> dict:
    with _state_lock:
        return dict(_state)


def load_report() -> dict | None:
    if not REPORT_PATH.exists():
        return None
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _strategy_jobs() -> list[tuple[dict, engine.CompiledFormula, dict]]:
    """全部公式策略 + 默认参数（跳过 within_n/board 等扫描参数）"""
    jobs = []
    for s in base.list_strategies():
        if s["kind"] != "formula":
            continue
        params = {p["key"]: p["default"] for p in s["params"]
                  if p["key"] not in ("within_n", "board", "exclude_st", "min_amount")}
        try:
            comp = engine.compile_formula(s["formula"])
        except Exception as e:  # noqa: BLE001
            log.warning("公式 %s 编译失败跳过: %s", s["id"], e)
            continue
        jobs.append((s, comp, params))
    return jobs


def run_backtest(months: float = 12, min_signals: int = 100,
                 save: bool = True) -> dict:
    """全市场 × 全公式策略回测。同步执行（约 5~15 分钟），由调用方决定线程/进程。"""
    with _state_lock:
        if _state["running"]:
            return {"running": True, "state": dict(_state)}
        _state.update(running=True, done=0, total=0,
                      started_at=datetime.now().isoformat(timespec="seconds"))

    t0 = time.time()
    bars = min(int(months * 21) + 40, _BARS)
    jobs = _strategy_jobs()
    codes_df = histstore.all_codes()
    codes = codes_df["code"].tolist()
    name_of = dict(zip(codes_df["code"], codes_df["name"]))

    # stats[sid] = {count, wins{h}, rets{h: [..]}} —— rets 只存和与平方和省内存，
    # 但盈亏比需要正负各自的均值 → 存正/负各自 (sum, count) 即可
    stats: dict[str, dict] = {
        j[0]["id"]: {"sid": j[0]["id"], "name": j[0]["name"], "cat": j[0]["category"],
                     "count": 0,
                     **{f"h{h}": {"win": 0, "n": 0, "pos_sum": 0.0, "pos_n": 0,
                                  "neg_sum": 0.0, "neg_n": 0} for h in _HORIZONS}}
        for j in jobs
    }
    def scan_stock(code: str) -> list[tuple[int, int, float]] | None:
        """返回 [(job_index, horizon, forward_ret), ...]；None=无数据"""
        df = histstore.read_kline(code, bars)
        if len(df) < _MIN_STOCK_BARS:
            return None
        n = len(df)
        cutoff = n - max(_HORIZONS)
        if cutoff <= 10:
            return None
        close = df["close"].to_numpy(dtype=float)
        out: list[tuple[int, int, float]] = []
        with np.errstate(all="ignore"):
            for ji, (_s, comp, params) in enumerate(jobs):
                try:
                    sig, _ = comp.eval(df, params)
                except Exception:  # noqa: BLE001
                    continue
                for i in sig.iloc[:cutoff].to_numpy().nonzero()[0]:
                    for h in _HORIZONS:
                        if i + h < n and close[i] > 0:
                            out.append((ji, h, close[i + h] / close[i] - 1))
        return out

    with _state_lock:
        _state["total"] = len(codes)

    def work(code: str):
        r = scan_stock(code)
        with _state_lock:
            _state["done"] += 1
        return code, r

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for _code, triples in pool.map(work, codes):
            if not triples:
                continue
            for ji, h, ret in triples:
                st = stats[jobs[ji][0]["id"]][f"h{h}"]
                st["n"] += 1
                if ret > 0:
                    st["win"] += 1
                if ret >= 0:
                    st["pos_sum"] += ret
                    st["pos_n"] += 1
                else:
                    st["neg_sum"] += ret
                    st["neg_n"] += 1
    # 5日信号数单独计（count = h5 的 n）
    for sid in stats:
        stats[sid]["count"] = stats[sid]["h5"]["n"]

    # ---- 汇总指标与排名 ----
    rows = []
    for sid, st in stats.items():
        if st["count"] == 0:
            continue
        h5 = st["h5"]
        win5 = h5["win"] / h5["n"] * 100 if h5["n"] else None
        avg5 = (h5["pos_sum"] + h5["neg_sum"]) / h5["n"] * 100 if h5["n"] else None
        avg_win5 = h5["pos_sum"] / h5["pos_n"] if h5["pos_n"] else 0.0
        avg_loss5 = abs(h5["neg_sum"] / h5["neg_n"]) if h5["neg_n"] else 0.0
        pf5 = avg_win5 / avg_loss5 if avg_loss5 > 0 else (99.0 if avg_win5 > 0 else 0.0)
        row = {"sid": sid, "name": st["name"], "cat": st["cat"], "signals": st["count"]}
        for h in _HORIZONS:
            hh = st[f"h{h}"]
            row[f"win{h}"] = round(hh["win"] / hh["n"] * 100, 1) if hh["n"] else None
        row["avg5"] = round(avg5, 2) if avg5 is not None else None
        row["pf5"] = round(pf5, 2)
        row["eligible"] = st["count"] >= min_signals
        # 综合分：胜率50% + 均收益30% + 盈亏比20%（仅在合格样本内归一化）
        row["_win5"] = win5 or 0
        row["_avg5"] = avg5 or -99
        row["_pf5"] = min(pf5, 10)
        rows.append(row)

    elig = [r for r in rows if r["eligible"]]

    def norm(vals, v):
        lo, hi = min(vals), max(vals)
        return (v - lo) / (hi - lo) if hi > lo else 0.5

    if elig:
        w5 = [r["_win5"] for r in elig]; a5 = [r["_avg5"] for r in elig]; p5 = [r["_pf5"] for r in elig]
        for r in rows:
            if r["eligible"]:
                r["score"] = round(norm(w5, r["_win5"]) * 50 + norm(a5, r["_avg5"]) * 30
                                   + norm(p5, r["_pf5"]) * 20, 1)
            else:
                r["score"] = None
        elig.sort(key=lambda r: -r["score"])
        for i, r in enumerate(elig, 1):
            r["rank"] = i

    for r in rows:
        for k in ("_win5", "_avg5", "_pf5"):
            r.pop(k, None)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_as_of": histstore.status().get("data_as_of"),
        "months": months,
        "stocks_scanned": len(codes),
        "strategies_total": len(rows),
        "min_signals": min_signals,
        "eligible": len(elig),
        "elapsed_s": round(time.time() - t0, 1),
        "top": elig[:30],
        "all": sorted(rows, key=lambda r: -(r["score"] or -1)),
    }
    if save:
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with _state_lock:
        _state.update(running=False, finished_at=datetime.now().isoformat(timespec="seconds"))
    log.info("回测完成：%d 策略 / %d 合格 / 耗时 %ss", len(rows), len(elig), report["elapsed_s"])
    return report
