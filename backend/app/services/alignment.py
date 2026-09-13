"""多因子数据对齐：目标序列 + 因子序列 → TimesFM 输入

遵循 TimesFM3 使用说明 §4.3：
- past_only_covariates 形状 (V, ctx_len)，与 context 等长
- 每个因子用自己历史段均值/标准差做 z-score（防泄漏），标准差过小置 1
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .. import config
from . import datasource

log = logging.getLogger("alignment")


@dataclass
class AlignedInput:
    dates: list[str]                       # 上下文窗口交易日
    context: np.ndarray                    # (ctx,) 目标收盘价 float32
    factor_names: list[str] = field(default_factory=list)
    past_only: np.ndarray | None = None    # (V, ctx) 已 z-score 的因子
    dropped_factors: list[dict] = field(default_factory=list)  # 因数据不足被剔除的因子


def build_aligned_input(
    target_code: str,
    factor_specs: list[dict],
    period: str = "daily",
    context_len: int = 180,
) -> AlignedInput:
    """拉取目标与因子数据，对齐到目标交易日，返回最近 context_len 步窗口"""
    period_def = config.PERIODS[period]
    # 预留对齐余量：目标请求 context_len*2.5 的自然日历史（周/月线更宽裕）
    days_back = int(context_len * period_def["calendar_days"] * 2.5) + 120
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    target_df = datasource.fetch_kline(target_code, period=period, start=start)
    if target_df.empty:
        raise RuntimeError(f"目标 {target_code} 无法获取 {period} 数据")
    if len(target_df) < 30:
        raise RuntimeError(
            f"目标 {target_code} {period} 数据不足（仅 {len(target_df)} 条），无法预测")

    target_df = target_df.dropna(subset=["close"]).sort_values("date")
    target_dates = target_df["date"].dt.strftime("%Y-%m-%d")
    target_index = pd.Index(target_dates)  # 对齐基准：目标交易日

    ctx_actual = min(context_len, len(target_df))
    window_idx = target_index[-ctx_actual:]

    context = target_df["close"].iloc[-ctx_actual:].to_numpy(dtype=np.float32)

    aligned_factors: dict[str, np.ndarray] = {}
    dropped: list[dict] = []
    for spec in factor_specs:
        fcode = spec["code"]
        if fcode == target_code:
            continue
        try:
            fdf = datasource.fetch_kline(fcode, period=period, start=start)
        except Exception as e:
            log.warning("因子 %s 拉取失败: %s", fcode, e)
            fdf = pd.DataFrame()
        if fdf.empty:
            dropped.append({**spec, "reason": "无数据"})
            continue
        s = fdf.dropna(subset=["close"]).set_index(
            fdf["date"].dt.strftime("%Y-%m-%d"))["close"]
        # 对齐到目标交易日：先 ffill 后 bfill（停牌日沿用前值）
        s_aligned = s.reindex(window_idx).ffill().bfill()
        valid_ratio = float(s_aligned.notna().mean())
        if valid_ratio < 0.9 or s_aligned.isna().all():
            dropped.append({**spec, "reason": f"历史覆盖不足({valid_ratio:.0%})"})
            continue
        s_aligned = s_aligned.bfill().ffill().fillna(0.0)
        aligned_factors[spec.get("name") or fcode] = s_aligned.to_numpy(dtype=np.float32)

    past_only = None
    factor_names: list[str] = []
    if aligned_factors:
        factor_names = list(aligned_factors.keys())
        mat = np.stack(list(aligned_factors.values()))  # (V, ctx)
        # 每个因子用自己上下文段统计量 z-score（§4.3）
        mu = mat.mean(axis=1, keepdims=True)
        sd = mat.std(axis=1, keepdims=True)
        sd = np.where(sd < 1e-8, 1.0, sd)
        past_only = ((mat - mu) / sd).astype(np.float32)

    return AlignedInput(
        dates=window_idx.tolist(),
        context=context,
        factor_names=factor_names,
        past_only=past_only,
        dropped_factors=dropped,
    )
