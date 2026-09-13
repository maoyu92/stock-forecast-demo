"""策略一：摇钱树·量比选股法（源自《早盘摇钱树选股法》docx 全量化）

两层漏斗：
1. 市场快筛 —— 量比降序 TopN + 涨幅区间 + 剔除 ST/非主板 + 成交额下限（对应原文操作步骤）
2. 深度精选 —— 7 因子打分排序（对应原文"重要的点"6 条 + 风险收益比）
"""
from typing import Optional

import pandas as pd

from . import emdata, indicators
from .base import ParamDef, StrategyDef, register

STRATEGY_ID = "moneytree"

# 因子默认权重（%），前端可在"因子权重"里调整
_W_VOLUME, _W_TREND, _W_LIMITUP, _W_RESIST, _W_MACD, _W_GAP, _W_RISK = 20, 20, 15, 15, 15, 10, 5


def prefilter(snap: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, int]:
    """第一层快筛，返回 (候选集, 快筛前股票数)"""
    df = snap[snap["price"].notna() & snap["volume_ratio"].notna()].copy()
    total = len(df)
    if p["exclude_st"]:
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
    if p["mainboard_only"]:
        df = df[df["code6"].str.startswith(("60", "00"))]
    df = df[(df["pct"] >= p["pct_min"]) & (df["pct"] <= p["pct_max"])]
    df = df[df["amount"] >= p["min_amount"] * 1e8]
    df = df.sort_values("volume_ratio", ascending=False).head(int(p["top_n"]))
    return df, total


def score_stock(kline: pd.DataFrame, snap_row: dict, p: dict) -> Optional[dict]:
    """第二层深度打分。硬条件不满足返回 None，否则返回结果条目。"""
    close = kline["close"]
    factors: list[dict] = []

    def add(fid: str, name: str, hit: Optional[bool], score: float, wmax: float, detail: str):
        # wmax=0 表示该因子被停用（权重 0），不参与计分
        factors.append({"id": fid, "name": name, "hit": hit,
                        "score": round(score, 1), "max": round(wmax, 1), "detail": detail})

    # ---- S1 现量一定要大：量比越大分越高（5 倍量比满分），成交额下限已在快筛保证
    vr = float(snap_row["volume_ratio"])
    s1 = min(vr / 5.0, 1.0) * p["w_volume"]
    add("volume", "量比/现量", vr >= 3, s1, p["w_volume"], f"量比 {vr:.2f}，成交额 {snap_row['amount'] / 1e8:.2f} 亿")

    # ---- S2 上涨趋势：价 > MA5 > MA10，且 MA20 斜率向上（三条各占 1/3）
    ma5, ma10, ma20 = indicators.ma(close, 5), indicators.ma(close, 10), indicators.ma(close, 20)
    c = float(close.iloc[-1])
    conds = [
        ("现价>MA5", c > ma5.iloc[-1]),
        ("MA5>MA10", ma5.iloc[-1] > ma10.iloc[-1]),
        ("MA20向上", indicators.slope_up(ma20)),
    ]
    hits = sum(1 for _, ok in conds if ok)
    s2 = hits / 3 * p["w_trend"]
    add("trend", "上涨趋势", hits == 3, s2, p["w_trend"],
        "、".join(f"{n}{'✓' if ok else '✗'}" for n, ok in conds))

    # ---- S3 前一交易日涨停封板：默认硬条件
    limit_hit, limit_date = indicators.eval_prev_limit_up(kline, snap_row["pct"])
    if p["require_prev_limit_up"] and not limit_hit:
        return None  # 硬条件：直接剔除
    s3 = p["w_limitup"] if limit_hit else 0.0
    add("limitup", "前日涨停封板", limit_hit, s3,
        p["w_limitup"] if not p["require_prev_limit_up"] else 0.0,
        f"{limit_date} {'涨停封板 ✓' if limit_hit else '未涨停 ✗'}"
        + ("（硬条件）" if p["require_prev_limit_up"] else ""))

    # ---- S4 压力位较远：距近 60 日高点空间越大分越高
    space = indicators.resistance_space(kline, 60)
    s4 = min(space / max(p["resist_space_min"], 0.1), 1.0) * p["w_resist"]
    add("resist", "压力位空间", space >= p["resist_space_min"], s4, p["w_resist"],
        f"距60日高点 {space:.1f}%（满分线 {p['resist_space_min']:.0f}%）")

    # ---- S5 MACD 红柱或刚金叉：近 3 日金叉满分，红柱 6 折
    dif, dea, _ = indicators.macd(close)
    golden = indicators.has_recent_golden_cross(dif, dea, 3)
    red = bool(dif.iloc[-1] > dea.iloc[-1])
    s5 = (p["w_macd"] if golden else (p["w_macd"] * 0.6 if red else 0.0))
    add("macd", "MACD动能", golden or red, s5, p["w_macd"],
        "近3日金叉 ✓" if golden else ("红柱（DIF>DEA）" if red else "绿柱，动能弱"))

    # ---- S6 缺口（降级实现）：近 5 日存在未回补的向上跳空缺口则加分
    gap = indicators.has_unfilled_gap_up(kline, 5)
    add("gap", "缺口形态", gap, p["w_gap"] if gap else 0.0, p["w_gap"],
        "近5日有未回补跳空缺口" if gap else "近5日无未回补缺口")

    # ---- S7 风险收益比：20 日波动率越低分越高（≤1% 满分，≥5% 零分）
    vol = indicators.daily_volatility_pct(kline, 20)
    s7 = 0.0 if pd.isna(vol) else max(min((5.0 - vol) / 4.0, 1.0), 0.0) * p["w_risk"]
    add("risk", "风险收益比", bool(pd.notna(vol) and vol <= 3), s7, p["w_risk"],
        f"20日波动率 {vol:.2f}%" if pd.notna(vol) else "波动率数据不足")

    max_total = sum(f["max"] for f in factors)
    score = sum(f["score"] for f in factors)
    score = round(score / max_total * 100, 1) if max_total > 0 else 0.0
    return {
        "code": emdata.to_bs_code(snap_row["code6"]),
        "name": snap_row["name"],
        "price": snap_row["price"], "pct": snap_row["pct"],
        "volume_ratio": vr, "turnover": snap_row["turnover"],
        "amount": snap_row["amount"],
        "score": score, "factors": factors,
    }


register(StrategyDef(
    id=STRATEGY_ID,
    name="摇钱树·量比选股法",
    description=("源自《早盘摇钱树选股法》：量比排行快筛 + 涨停/趋势/MACD 等 7 因子精选打分。"
                 "适合早盘量比异动、前一交易日涨停的强势股。"),
    source="《早盘摇钱树选股法（秘籍）》docx",
    params=[
        ParamDef("top_n", "量比排行取前 N", "number", 30, 10, 100, 1, "只",
                 "第一层快筛：全市场按量比降序取前 N 只进入深度打分"),
        ParamDef("pct_min", "涨幅下限", "number", 1.0, 0, 10, 0.5, "%", "快筛：涨跌幅区间下限（原文：低于1%删除）"),
        ParamDef("pct_max", "涨幅上限", "number", 5.0, 0, 10, 0.5, "%", "快筛：涨跌幅区间上限（原文：超5%删除）"),
        ParamDef("min_amount", "成交额下限", "number", 1.0, 0, 50, 0.5, "亿", "快筛：保证现量足够大"),
        ParamDef("exclude_st", "剔除 ST/*ST", "bool", True, description="原文：ST 与 *ST 全部删除"),
        ParamDef("mainboard_only", "仅沪深主板", "bool", True, description="原文：30/68/83 开头全部删除，仅保留 60/00"),
        ParamDef("require_prev_limit_up", "前日涨停(硬条件)", "bool", True,
                 description="开启后未涨停的股票直接剔除；关闭则降为加分项，可扩大结果范围"),
        ParamDef("resist_space_min", "压力位满分线", "number", 10.0, 3, 30, 1, "%",
                 "距近60日最高价的空间达到该值即得满分"),
        ParamDef("w_volume", "权重·量比现量", "number", _W_VOLUME, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_trend", "权重·上涨趋势", "number", _W_TREND, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_limitup", "权重·前日涨停", "number", _W_LIMITUP, 0, 100, 5, "%",
                 "仅当'前日涨停'不是硬条件时参与计分"),
        ParamDef("w_resist", "权重·压力位空间", "number", _W_RESIST, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_macd", "权重·MACD", "number", _W_MACD, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_gap", "权重·缺口形态", "number", _W_GAP, 0, 100, 5, "%", "因子权重"),
        ParamDef("w_risk", "权重·风险收益比", "number", _W_RISK, 0, 100, 5, "%", "因子权重"),
    ],
    run=None,  # 编排由包 __init__ 统一实现（prefilter + score_stock 两段式）
))
