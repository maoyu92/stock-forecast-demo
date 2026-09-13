"""公式型选股 runner —— 基于「本地历史K线仓库」的全市场公式扫描

与实时快照策略（moneytree/smartmoney）不同，公式策略完全跑在本地数据上：
    读 kline_daily（最近 ~320 根日K）→ 公式向量化求值 → 信号落在最近 N 根内即命中
    → 强度公式（若有）做百分位打分 → 排序输出。

单只股票单公式毫秒级，全市场 5000 只 × 1 公式在 10 秒量级完成（8 线程）。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from ... import histstore
from . import engine

log = logging.getLogger("screener.formula_runner")

_BARS = 320          # 每只股票载入的K线根数（公式最长周期 250 + 斜率余量）
_MIN_BARS = 80       # 少于该根数直接跳过（次新股指标不可信）
_STALE_DAYS = 10     # 数据滞后超过该天数的股票跳过（长期停牌）
_WORKERS = 8
_MAX_RESULTS = 300


def _scan_one(comp, code: str, name: str, params: dict, has_strength: bool) -> dict | None:
    """单只股票：读K线 → 公式求值 → 信号判定。返回原始命中信息或 None

    comp 为「主公式 + 可选 STRENGTH 输出线」的合并公式；
    信号取倒数第二/第一条输出线，强度从详情字典的 STRENGTH 读取。
    """
    df = histstore.read_kline(code, _BARS)
    if len(df) < _MIN_BARS:
        return None
    lag_days = (pd.Timestamp.now() - df["date"].iloc[-1]).days
    if lag_days > _STALE_DAYS:
        return None

    sig_out = -2 if has_strength else -1
    try:
        sig, _ = comp.eval(df, params, out=sig_out)
    except Exception as e:  # noqa: BLE001 —— 单只失败不阻断
        log.warning("公式求值失败 %s: %s", code, e)
        return None
    if not bool(sig.iloc[-1]):
        return None

    within = int(params.get("within_n", 1))
    hits = sig.tail(within).to_numpy().nonzero()[0]
    if len(hits) == 0:
        return None
    at = len(sig) - within + int(hits[-1])          # 信号所在K线（最后一根有效命中）
    _, detail = comp.eval(df, params, at=at)        # 在信号K线处取详情值（含 STRENGTH）

    row = df.iloc[at]
    prev_close = float(df["close"].iloc[at - 1]) if at >= 1 else float(row["close"])
    price = float(row["close"])
    pct = (price / prev_close - 1) * 100 if prev_close > 0 else 0.0

    strength = detail.get("STRENGTH") if has_strength else None
    amount = float(row["amount"]) if "amount" in df else 0.0
    return {
        "code": code, "name": name, "price": price, "pct": round(pct, 2),
        "signal_date": str(row["date"].date()), "strength": strength,
        "amount": amount, "detail": detail,
    }


def run_formula_strategy(st, params: dict) -> tuple[list[dict], dict]:
    """执行公式型选股。返回 (结果列表, 元信息)，与快照策略接口一致；
    落库与响应组装由 screener.run_screen 统一完成。"""
    comp = engine.compile_formula(
        st.formula + ("\nSTRENGTH:" + st.strength + ";" if st.strength else ""))
    has_strength = bool(st.strength)

    codes_df = histstore.all_codes()
    if codes_df.empty:
        raise RuntimeError(
            "本地历史K线仓库为空：请先在「数据管理」面板同步历史数据"
            "（或运行 scripts/sync_history.py）")

    # 板块 / ST / 名称过滤
    codes_df = codes_df.copy()
    codes_df["code6"] = codes_df["code"].str.split(".").str[-1]
    board = str(params.get("board", "全部"))
    if board == "主板":
        codes_df = codes_df[codes_df["code6"].str.startswith(("60", "00"))]
    elif board == "创业板":
        codes_df = codes_df[codes_df["code6"].str.startswith("30")]
    elif board == "科创板":
        codes_df = codes_df[codes_df["code6"].str.startswith("68")]
    if params.get("exclude_st", True):
        codes_df = codes_df[~codes_df["name"].str.upper().str.contains("ST", na=False)]

    rows = list(codes_df[["code", "name"]].itertuples(index=False, name=None))
    total = len(rows)
    t0 = time.time()

    hits: list[dict] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for r in pool.map(lambda x: _scan_one(comp, x[0], x[1], params, has_strength), rows):
            if r is not None:
                hits.append(r)

    # 成交额过滤
    min_amt = float(params.get("min_amount", 0) or 0) * 1e8
    if min_amt > 0:
        hits = [h for h in hits if h["amount"] >= min_amt]

    # 强度百分位 → 0~100 分；无强度公式一律 100
    strengths = [h["strength"] for h in hits if h["strength"] is not None]
    for h in hits:
        if strengths and h["strength"] is not None:
            below = sum(1 for s in strengths if s < h["strength"])
            h["score"] = round(below / len(strengths) * 100, 1)
        else:
            h["score"] = 100.0
    hits.sort(key=lambda h: (-h["score"], -h["pct"]))
    hits = hits[:_MAX_RESULTS]

    # 渲染命中详情
    tpl = st.detail_tpl or ""
    results = []
    for i, h in enumerate(hits, 1):
        detail_txt = ""
        if tpl:
            try:
                vals = {k: v for k, v in h["detail"].items()}
                detail_txt = tpl.format_map(_SafeDict(vals))
            except Exception:  # noqa: BLE001
                detail_txt = ""
        results.append({
            "rank": i,
            "code": h["code"], "name": h["name"],
            "price": round(h["price"], 2), "pct": h["pct"],
            "volume_ratio": None, "turnover": None,
            "amount": h["amount"], "score": h["score"],
            "signal_date": h["signal_date"],
            "detail": detail_txt,
            "factors": [{
                "id": st.id, "name": st.name, "hit": True,
                "score": h["score"], "max": 100.0,
                "detail": detail_txt or f"信号日 {h['signal_date']}",
            }],
        })

    elapsed_ms = int((time.time() - t0) * 1000)
    status = histstore.status()
    meta = {
        "snapshot_time": status.get("data_as_of") or "",
        "total_screened": total,
        "candidates": len(results),
    }
    return results, meta


class _SafeDict(dict):
    """模板缺变量时不抛错，显示为空"""

    def __missing__(self, key):
        return ""


# ============================ 多策略组合扫描 ============================

def _multi_scan_one(entries, excl_entries, code: str, name: str,
                    params_by_sid: dict, excl_params: dict) -> dict | None:
    """单只股票：读一次K线，评估全部主策略与排除策略公式。

    entries: [(st, comp, has_strength)]；返回 None=无任何主信号。
    """
    df = histstore.read_kline(code, _BARS)
    if len(df) < _MIN_BARS:
        return None
    if (pd.Timestamp.now() - df["date"].iloc[-1]).days > _STALE_DAYS:
        return None

    hits = []
    for st, comp, has_strength in entries:
        p = params_by_sid[st.id]
        out = -2 if has_strength else -1
        try:
            sig, _ = comp.eval(df, p, out=out)
        except Exception as e:  # noqa: BLE001 —— 单策略失败不影响其它策略
            log.warning("组合扫描 %s 求值失败 %s: %s", code, st.id, e)
            continue
        within = int(p.get("within_n", 1))
        idx = sig.tail(within).to_numpy().nonzero()[0]
        if len(idx) == 0:
            continue
        at = len(sig) - within + int(idx[-1])
        _, detail = comp.eval(df, p, at=at)
        hits.append({
            "sid": st.id, "name": st.name, "tpl": st.detail_tpl,
            "at": at, "detail": detail,
            "strength": detail.get("STRENGTH") if has_strength else None,
        })
    if not hits:
        return None

    excluded = False
    for st, comp, has_strength in excl_entries:
        p = excl_params[st.id]
        out = -2 if has_strength else -1
        try:
            sig, _ = comp.eval(df, p, out=out)
        except Exception:  # noqa: BLE001
            continue
        within = int(p.get("within_n", 1))
        if sig.tail(within).any():
            excluded = True
            break

    at_max = max(h["at"] for h in hits)
    row = df.iloc[at_max]
    prev_close = float(df["close"].iloc[at_max - 1]) if at_max >= 1 else float(row["close"])
    return {
        "code": code, "name": name,
        "price": float(row["close"]),
        "pct": round((float(row["close"]) / prev_close - 1) * 100, 2) if prev_close > 0 else 0.0,
        "signal_date": str(row["date"].date()),
        "amount": float(row.get("amount", 0.0) or 0.0),
        "hits": hits, "excluded": excluded,
    }


def run_multi_strategy(defs, params_by_sid: dict, excl_defs, excl_params: dict,
                       combine: str = "or") -> tuple[list[dict], dict]:
    """多策略组合扫描：全部公式在同一次K线读取中评估，再做集合运算。

    combine: or=并集(任一命中) / and=交集(全部命中)；excl_defs 命中的股票被剔除。
    返回 (结果列表, 元信息)。
    """
    codes_df = histstore.all_codes()
    if codes_df.empty:
        raise RuntimeError(
            "本地历史K线仓库为空：请先在「数据管理」面板同步历史数据"
            "（或运行 scripts/sync_history.py）")

    # 板块/ST 过滤沿用第一个策略的公共参数（组合模式下各策略公共参数一致）
    p0 = params_by_sid[defs[0].id]
    codes_df = codes_df.copy()
    codes_df["code6"] = codes_df["code"].str.split(".").str[-1]
    board = str(p0.get("board", "全部"))
    if board == "主板":
        codes_df = codes_df[codes_df["code6"].str.startswith(("60", "00"))]
    elif board == "创业板":
        codes_df = codes_df[codes_df["code6"].str.startswith("30")]
    elif board == "科创板":
        codes_df = codes_df[codes_df["code6"].str.startswith("68")]
    if p0.get("exclude_st", True):
        codes_df = codes_df[~codes_df["name"].str.upper().str.contains("ST", na=False)]

    entries = [(st, engine.compile_formula(
        st.formula + ("\nSTRENGTH:" + st.strength + ";" if st.strength else "")),
        bool(st.strength)) for st in defs]
    excl_entries = [(st, engine.compile_formula(
        st.formula + ("\nSTRENGTH:" + st.strength + ";" if st.strength else "")),
        bool(st.strength)) for st in excl_defs]

    rows = list(codes_df[["code", "name"]].itertuples(index=False, name=None))
    total = len(rows)
    t0 = time.time()

    scanned: list[dict] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for r in pool.map(lambda x: _multi_scan_one(
                entries, excl_entries, x[0], x[1], params_by_sid, excl_params), rows):
            if r is not None:
                scanned.append(r)

    # 排除集 + 组合方式
    excluded_n = sum(1 for r in scanned if r["excluded"])
    scanned = [r for r in scanned if not r["excluded"]]
    need = len(defs) if combine == "and" else 1
    picked = [r for r in scanned if len(r["hits"]) >= need]

    # 成交额过滤（组合模式同样适用，取第一个策略的公共参数）
    min_amt = float(p0.get("min_amount", 0) or 0) * 1e8
    if min_amt > 0:
        picked = [r for r in picked if r["amount"] >= min_amt]

    # 每策略内部的强度百分位
    strengths_by_sid: dict[str, list[float]] = {}
    for r in picked:
        for h in r["hits"]:
            if h["strength"] is not None:
                strengths_by_sid.setdefault(h["sid"], []).append(h["strength"])
    for r in picked:
        scores = []
        for h in r["hits"]:
            ss = strengths_by_sid.get(h["sid"])
            h["score"] = round(sum(1 for s in ss if s < h["strength"]) / len(ss) * 100, 1) \
                if ss and h["strength"] is not None else None
            if h["score"] is not None:
                scores.append(h["score"])
        if combine == "and":
            r["score"] = round(sum(scores) / len(scores), 1) if scores else 100.0
        else:
            r["score"] = max(scores) if scores else 100.0

    picked.sort(key=lambda r: (-r["score"], -r["pct"]))
    picked = picked[:_MAX_RESULTS]

    results = []
    for i, r in enumerate(picked, 1):
        factors = []
        parts = []
        for h in r["hits"]:
            txt = ""
            if h["tpl"]:
                try:
                    txt = h["tpl"].format_map(_SafeDict(h["detail"]))
                except Exception:  # noqa: BLE001
                    txt = ""
            factors.append({
                "id": h["sid"], "name": h["name"], "hit": True,
                "score": h["score"] if h["score"] is not None else 100.0,
                "max": 100.0,
                "detail": txt or f"信号日 {r['signal_date']}",
            })
            parts.append(f"{h['name']}: {txt}" if txt else h["name"])
        results.append({
            "rank": i,
            "code": r["code"], "name": r["name"],
            "price": round(r["price"], 2), "pct": r["pct"],
            "volume_ratio": None, "turnover": None,
            "amount": r["amount"], "score": r["score"],
            "signal_date": r["signal_date"],
            "detail": "；".join(parts),
            "factors": factors,
        })

    per_strategy = {}
    for r in scanned:
        for h in r["hits"]:
            per_strategy[h["sid"]] = per_strategy.get(h["sid"], 0) + 1

    meta = {
        "snapshot_time": histstore.status().get("data_as_of") or "",
        "total_screened": total,
        "candidates": len(results),
        "per_strategy": per_strategy,
        "excluded": excluded_n,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    return results, meta
