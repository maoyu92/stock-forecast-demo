"""策略二：主力动向（游资/私募/险资/庄家主题的公开指标近似实现）

来源说明：原 .tn6 为通达信完全加密公式，无法还原源码（详见 PRD）。
本方法以"主力资金动向"为主题，用公开可查的量价与资金流指标重建：
连续放量、量价齐升、换手活跃、突破20日新高、主力净流入。
"""
from typing import Optional

from . import emdata, indicators
from .base import ParamDef, StrategyDef, register

STRATEGY_ID = "smartmoney"

_W_VOLUME, _W_PRICEVOL, _W_TURNOVER, _W_BREAKOUT, _W_INFLOW = 20, 15, 15, 20, 30


def prefilter(snap, p: dict) -> tuple:
    """第一层快筛：涨幅区间 + 活跃度 + 剔除 ST/非主板，按量比降序取 TopN"""
    df = snap[snap["price"].notna() & snap["volume_ratio"].notna()].copy()
    total = len(df)
    if p["exclude_st"]:
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
    if p["mainboard_only"]:
        df = df[df["code6"].str.startswith(("60", "00"))]
    df = df[(df["pct"] >= p["pct_min"]) & (df["pct"] <= p["pct_max"])]
    df = df[df["amount"] >= p["min_amount"] * 1e8]
    df = df[df["turnover"] >= 1.0]  # 过冷门股不进深度分析
    df = df.sort_values("volume_ratio", ascending=False).head(int(p["top_n"]))
    return df, total


def score_stock(kline, snap_row: dict, p: dict) -> Optional[dict]:
    close, vol = kline["close"], kline["volume"]
    factors: list[dict] = []

    def add(fid, name, hit, score, wmax, detail):
        factors.append({"id": fid, "name": name, "hit": hit,
                        "score": round(score, 1), "max": round(wmax, 1), "detail": detail})

    # ---- M1 连续放量：近 3 日成交量均 > 前 5 日均量 × 1.5
    need = int(p["burst_days"])
    vol_hits = 0
    n = len(vol)
    for i in range(n - need, n):
        base = vol.iloc[i - 5:i].mean()
        if base > 0 and vol.iloc[i] > 1.5 * base:
            vol_hits += 1
    s1 = vol_hits / need * p["w_volume"]
    add("burst", "连续放量", vol_hits == need, s1, p["w_volume"],
        f"近{need}日中 {vol_hits} 日放量超1.5倍")

    # ---- M2 量价齐升：近 3 日收阳且量增的天数
    pv_hits = 0
    for i in range(n - need, n):
        if close.iloc[i] > close.iloc[i - 1] and vol.iloc[i] > vol.iloc[i - 1]:
            pv_hits += 1
    s2 = pv_hits / need * p["w_pricevol"]
    add("pricevol", "量价齐升", pv_hits == need, s2, p["w_pricevol"],
        f"近{need}日中 {pv_hits} 日量价齐升")

    # ---- M3 换手活跃：区间 [min,max] 满分，向两侧线性衰减至 0
    to = float(snap_row["turnover"])
    tmin, tmax = p["turnover_min"], p["turnover_max"]
    if to >= tmin and to <= tmax:
        s3, hit3 = p["w_turnover"], True
    elif to < tmin:
        s3 = max(to / tmin, 0.0) * p["w_turnover"] if to > 0 else 0.0
        hit3 = to >= tmin * 0.5
    else:
        s3 = max((tmax * 1.5 - to) / (tmax * 0.5), 0.0) * p["w_turnover"]
        hit3 = to <= tmax * 1.25
    add("turnover", "换手活跃", hit3, s3, p["w_turnover"],
        f"换手率 {to:.2f}%（活跃区间 {tmin:.0f}~{tmax:.0f}%）")

    # ---- M4 突破形态：收盘价创 20 日新高满分，距新高 3% 内半分
    hh = close.iloc[-21:-1].max()
    c = float(close.iloc[-1])
    if c >= hh:
        s4, hit4, note = p["w_breakout"], True, "已突破20日新高 ✓"
    elif c >= hh * 0.97:
        s4, hit4, note = p["w_breakout"] * 0.5, True, f"距20日新高 {(hh / c - 1) * 100:.1f}%"
    else:
        s4, hit4, note = 0.0, False, f"距20日新高 {(hh / c - 1) * 100:.1f}%"
    add("breakout", "突破新高", hit4, s4, p["w_breakout"], note)

    # ---- M5 主力净流入：近 N 日主力净流入合计为正满分（接口不可用时自动剔除权重）
    flow = emdata.fetch_fund_flow(snap_row["code6"], int(p["flow_days"]))
    if flow is None:
        add("inflow", "主力净流入", None, 0.0, 0.0, "资金流数据不可用，已剔除该因子权重")
    else:
        total_net = sum(x["main_net"] for x in flow)
        s5 = p["w_inflow"] if total_net > 0 else 0.0
        add("inflow", "主力净流入", total_net > 0, s5, p["w_inflow"],
            f"近{p['flow_days']}日主力净流入 {total_net / 1e4:+,.0f} 万")

    max_total = sum(f["max"] for f in factors)
    score = sum(f["score"] for f in factors)
    score = round(score / max_total * 100, 1) if max_total > 0 else 0.0
    return {
        "code": emdata.to_bs_code(snap_row["code6"]),
        "name": snap_row["name"],
        "price": snap_row["price"], "pct": snap_row["pct"],
        "volume_ratio": float(snap_row["volume_ratio"]),
        "turnover": to, "amount": snap_row["amount"],
        "score": score, "factors": factors,
    }


register(StrategyDef(
    id=STRATEGY_ID,
    name="主力动向",
    description=("以「游资/私募/险资/庄家」主力资金动向为主题的近似策略：连续放量、量价齐升、"
                 "换手活跃、突破新高、主力净流入五因子打分。"
                 "原 .tn6 公式为完全加密格式无法还原，本实现基于公开指标，参数可调待校准。"),
    source=".tn6 主题近似（公开指标重建）",
    params=[
        ParamDef("top_n", "量比排行取前 N", "number", 50, 10, 150, 5, "只",
                 "第一层快筛：按量比降序取前 N 只进入深度打分"),
        ParamDef("pct_min", "涨幅下限", "number", 0.0, -5, 10, 0.5, "%", "快筛：涨跌幅区间下限"),
        ParamDef("pct_max", "涨幅上限", "number", 7.0, 0, 10, 0.5, "%", "快筛：涨跌幅区间上限"),
        ParamDef("min_amount", "成交额下限", "number", 2.0, 0, 50, 0.5, "亿", "快筛：保证资金关注度"),
        ParamDef("exclude_st", "剔除 ST/*ST", "bool", True, description="剔除风险警示股"),
        ParamDef("mainboard_only", "仅沪深主板", "bool", True, description="仅保留 60/00 开头主板股"),
        ParamDef("burst_days", "放量观察天数", "number", 3, 2, 5, 1, "日", "连续放量/量价齐升的观察窗口"),
        ParamDef("turnover_min", "换手活跃下限", "number", 3.0, 1, 10, 0.5, "%", "换手率活跃区间下限（满分线）"),
        ParamDef("turnover_max", "换手活跃上限", "number", 15.0, 5, 30, 1, "%", "换手率活跃区间上限（满分线，过热降分）"),
        ParamDef("flow_days", "资金流天数", "number", 3, 1, 10, 1, "日", "主力净流入合计的天数窗口"),
        ParamDef("w_volume", "权重·连续放量", "number", _W_VOLUME, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_pricevol", "权重·量价齐升", "number", _W_PRICEVOL, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_turnover", "权重·换手活跃", "number", _W_TURNOVER, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_breakout", "权重·突破新高", "number", _W_BREAKOUT, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_inflow", "权重·主力净流入", "number", _W_INFLOW, 0, 100, 5, "%", "因子权重"),
    ],
    run=None,
))
