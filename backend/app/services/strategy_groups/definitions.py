"""5 个完整买卖策略组定义"""
from __future__ import annotations

from .base import StrategyGroupDef, register


register(StrategyGroupDef(
    id="trend_breakout",
    name="趋势共振突破组",
    description="海龟/放量突破 + MACD 多头确认，趋势市进攻；ATR 追踪止损与均线破位退出。",
    entry_ids=["turtle_trend", "vol_break_20"],
    entry_combine="or",
    risk_ids=["risk_duandao", "risk_fd_top", "risk_rub_high"],
    exit_kind="trend",
    max_positions=3,
    max_weight=0.18,
    risk_per_trade=0.008,
    hard_stop_pct=0.08,
    stop_atr_mult=3.0,
    trail_drawdown_pct=0.12,
    max_holding_days=30,
    time_exit_min_return_pct=0.01,
    min_amount=1.0,
))

register(StrategyGroupDef(
    id="pullback_trend",
    name="均线回踩趋势组",
    description="强势股回踩布林中轨或缩量回调，降低追高；跌破中期均线退出。",
    entry_ids=["boll_strong_pullback", "vol_shrink_pullback"],
    entry_combine="or",
    risk_ids=["risk_duandao", "risk_fd_top"],
    exit_kind="pullback",
    max_positions=3,
    max_weight=0.15,
    risk_per_trade=0.006,
    hard_stop_pct=0.07,
    stop_atr_mult=2.5,
    trail_drawdown_pct=0.10,
    max_holding_days=25,
    time_exit_min_return_pct=0.0,
    min_amount=1.0,
))

register(StrategyGroupDef(
    id="oversold_rebound",
    name="超跌反弹组",
    description="布林/RSI 超卖共振，放量站上 5 日线；快进快出，严格时间止损。",
    entry_ids=["res_boll_rsi", "vol_cross_ma5"],
    entry_combine="or",
    risk_ids=["risk_duandao", "risk_fd_top"],
    exit_kind="oversold",
    max_positions=3,
    max_weight=0.12,
    risk_per_trade=0.005,
    hard_stop_pct=0.07,
    stop_atr_mult=2.0,
    trail_drawdown_pct=0.08,
    max_holding_days=10,
    time_exit_min_return_pct=0.03,
    min_amount=0.5,
))

register(StrategyGroupDef(
    id="capital_momentum",
    name="资金/游资动量组",
    description="游资进场或机构拉升近似信号；高波动，必须配合紧止损。",
    entry_ids=["youzijinchang", "zijin_lasheng"],
    entry_combine="or",
    risk_ids=["risk_duandao", "risk_rub_high"],
    exit_kind="momentum",
    max_positions=2,
    max_weight=0.18,
    risk_per_trade=0.008,
    hard_stop_pct=0.07,
    stop_atr_mult=2.0,
    trail_drawdown_pct=0.10,
    max_holding_days=15,
    time_exit_min_return_pct=0.02,
    min_amount=2.0,
))

register(StrategyGroupDef(
    id="timesfm_enhanced",
    name="TimesFM 预测增强组",
    description="非 mock 的历史预测记录 + 全多头技术确认；预测覆盖不足时不产生交易。",
    entry_ids=["res_all_bull"],
    entry_combine="and",
    risk_ids=["risk_duandao", "risk_fd_top"],
    exit_kind="model",
    max_positions=2,
    max_weight=0.15,
    risk_per_trade=0.006,
    hard_stop_pct=0.07,
    stop_atr_mult=2.5,
    trail_drawdown_pct=0.10,
    max_holding_days=20,
    time_exit_min_return_pct=0.0,
    min_amount=1.0,
    requires_forecast=True,
))
