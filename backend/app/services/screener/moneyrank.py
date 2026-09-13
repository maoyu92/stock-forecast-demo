"""策略：主力净流入榜（同花顺"主力净流入排行"式玩法）

与 smartmoney（主力动向，逐股拉资金流验证）不同，本策略先用东财聚合接口
把全市场按"当日主力净流入（超大单+大单）"降序排行取前 N，再逐只拉本地K线深度打分：
    M1 主力净流入额（主因子）   M2 主力净占比        M3 超大单主导度
    M4 量价配合（放量阳线）     M5 趋势（C>MA5>MA10） M6 强势状态（对应"机构活跃度"标签）
对应同花顺"机构活跃度"标签的近似：收盘 > MA60 → "大牛线上"；> MA20 → "强势线上"。
"""
from typing import Optional

import pandas as pd

from . import emdata, indicators
from .base import ParamDef, StrategyDef, register

STRATEGY_ID = "moneyrank"

_W_FLOW, _W_PCT, _W_SUPER, _W_PV, _W_TREND, _W_STRONG = 35, 15, 10, 15, 15, 10


def prefilter(snap: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, int]:
    """第一层：东财聚合接口按主力净流入排行取前 N + 基础过滤。
    （不使用全市场快照——排行本身来自资金流聚合接口）"""
    rank = emdata.fund_flow_rank(int(p["top_n"]))
    total = len(snap)
    df = rank[rank["price"].notna()].copy()
    if p["exclude_st"]:
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
    if p["mainboard_only"]:
        df = df[df["code6"].str.startswith(("60", "00"))]
    df = df[(df["pct"] >= p["pct_min"]) & (df["pct"] <= p["pct_max"])]
    df = df[df["main_net"] >= p["min_inflow"] * 1e8]
    return df, total


def score_stock(kline: pd.DataFrame, snap_row: dict, p: dict) -> Optional[dict]:
    """第二层：K线深度打分（主力资金面为主 + 量价/趋势确认）"""
    close = kline["close"]
    factors: list[dict] = []

    def add(fid, name, hit, score, wmax, detail):
        factors.append({"id": fid, "name": name, "hit": hit,
                        "score": round(score, 1), "max": round(wmax, 1), "detail": detail})

    main_net = float(snap_row["main_net"])
    main_pct = float(snap_row.get("main_pct") or 0)
    super_net = float(snap_row.get("super_net") or 0)

    # ---- M1 主力净流入额：≥min_inflow 保底（快筛已保证），≥5亿 满分
    s1 = min(main_net / 1e8 / 5.0, 1.0) * p["w_flow"]
    add("flow", "主力净流入", main_net >= 1e8, s1, p["w_flow"],
        f"当日主力净流入 {main_net / 1e8:.2f} 亿（超大单 {super_net / 1e8:.2f} 亿）")

    # ---- M2 主力净占比：≥10% 满分，≥5% 六折
    s2 = (p["w_pct"] if main_pct >= 10 else p["w_pct"] * 0.6 if main_pct >= 5 else 0.0)
    add("mainpct", "主力净占比", main_pct >= 5, s2, p["w_pct"],
        f"主力净流入占成交额 {main_pct:.1f}%")

    # ---- M3 超大单主导度：超大单占主力净流入 ≥50% 满分（机构级大单主导）
    super_ratio = super_net / main_net * 100 if main_net > 0 else 0.0
    s3 = min(max(super_ratio, 0) / 50.0, 1.0) * p["w_super"]
    add("super", "超大单主导", super_ratio >= 50, s3, p["w_super"],
        f"超大单占主力净流入 {super_ratio:.0f}%")

    # ---- M4 量价配合：放量阳线（≥1.5×5日均量 且 收阳）
    vr5 = float(kline["volume"].iloc[-1]) / (float(kline["volume"].tail(6).head(5).mean()) or 1)
    yang = close.iloc[-1] > float(kline["open"].iloc[-1])
    pv = vr5 >= 1.5 and yang
    s4 = (p["w_pv"] if pv else p["w_pv"] * 0.4 if yang else 0.0)
    add("pv", "量价配合", pv, s4, p["w_pv"],
        f"量比5日均量 {vr5:.2f}，{'阳线' if yang else '阴线'}")

    # ---- M5 趋势：C>MA5>MA10 且 MA20 向上（三条各占 1/3）
    ma5, ma10, ma20 = indicators.ma(close, 5), indicators.ma(close, 10), indicators.ma(close, 20)
    c = float(close.iloc[-1])
    conds = [("现价>MA5", c > ma5.iloc[-1]), ("MA5>MA10", ma5.iloc[-1] > ma10.iloc[-1]),
             ("MA20向上", indicators.slope_up(ma20))]
    hits = sum(1 for _, ok in conds if ok)
    s5 = hits / 3 * p["w_trend"]
    add("trend", "趋势确认", hits == 3, s5, p["w_trend"],
        "、".join(f"{n}{'✓' if ok else '✗'}" for n, ok in conds))

    # ---- M6 强势状态（近似同花顺"机构活跃度"标签）：C>MA60="大牛线上"，C>MA20="强势线上"
    ma60 = indicators.ma(close, 60)
    on_bull = pd.notna(ma60.iloc[-1]) and c > ma60.iloc[-1]
    on_strong = pd.notna(ma20.iloc[-1]) and c > ma20.iloc[-1]
    s6 = (p["w_strong"] if on_bull else p["w_strong"] * 0.6 if on_strong else 0.0)
    tag = "大牛线上" if on_bull else ("强势线上" if on_strong else "弱势")
    add("strength", "机构活跃度", on_bull or on_strong, s6, p["w_strong"],
        f"{tag}（{'MA60' if on_bull else 'MA20'}之上）")

    max_total = sum(f["max"] for f in factors)
    score = sum(f["score"] for f in factors)
    score = round(score / max_total * 100, 1) if max_total > 0 else 0.0
    tag_label = f"{tag}·主力净流入{main_net / 1e8:.1f}亿"
    return {
        "code": emdata.to_bs_code(snap_row["code6"]),
        "name": snap_row["name"],
        "price": snap_row["price"], "pct": snap_row["pct"],
        "volume_ratio": None, "turnover": snap_row.get("turnover"),
        "amount": snap_row["amount"],
        "score": score, "factors": factors,
        "tag": tag_label,
    }


register(StrategyDef(
    id=STRATEGY_ID,
    name="主力净流入榜",
    description=("同花顺「主力净流入排行」式玩法：全市场按当日主力净流入（超大单+大单，东财口径）"
                 "降序取前 N，再叠加量价/趋势/强势状态打分。适合跟踪大资金当日主攻方向。"),
    source="同花顺主力净流入排行（数据：东财资金流聚合接口）",
    params=[
        ParamDef("top_n", "净流入排行取前 N", "number", 50, 10, 200, 5, "只",
                 "第一层：全市场按当日主力净流入降序取前 N 只进入深度打分"),
        ParamDef("pct_min", "涨幅下限", "number", -2.0, -10, 10, 0.5, "%",
                 "过滤：允许小跌（资金逆势吸筹），默认 -2%"),
        ParamDef("pct_max", "涨幅上限", "number", 8.0, 0, 11, 0.5, "%", "过滤：涨幅过高追入风险大"),
        ParamDef("min_inflow", "主力净流入下限", "number", 1.0, 0, 50, 0.5, "亿",
                 "过滤：当日主力净流入低于该值剔除"),
        ParamDef("exclude_st", "剔除 ST/*ST", "bool", True),
        ParamDef("mainboard_only", "仅沪深主板", "bool", False,
                 description="开启后仅保留 60/00 开头（默认包含创业板/科创板）"),
        ParamDef("w_flow", "权重·主力净流入", "number", _W_FLOW, 0, 100, 5, "%"),
        ParamDef("w_pct", "权重·主力净占比", "number", _W_PCT, 0, 100, 5, "%"),
        ParamDef("w_super", "权重·超大单主导", "number", _W_SUPER, 0, 100, 5, "%"),
        ParamDef("w_pv", "权重·量价配合", "number", _W_PV, 0, 100, 5, "%"),
        ParamDef("w_trend", "权重·趋势确认", "number", _W_TREND, 0, 100, 5, "%"),
        ParamDef("w_strong", "权重·强势状态", "number", _W_STRONG, 0, 100, 5, "%"),
    ],
    run=None,  # 编排由包 __init__ 统一实现（prefilter + score_stock 两段式）
))
