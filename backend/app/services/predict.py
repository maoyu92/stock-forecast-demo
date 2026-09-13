"""预测编排：数据对齐 → 引擎回退链推理 → 组装结果 → 落库"""
import logging
from datetime import timedelta

import pandas as pd

from .. import config, db
from .alignment import build_aligned_input
from .datasource import next_trade_dates
from .inference import InferenceError, engine_candidates

log = logging.getLogger("predict")


def _forecast_dates(last_date: str, period: str, horizon: int) -> list[str]:
    if period == "daily":
        return next_trade_dates(last_date, horizon)
    step = config.PERIODS[period]["calendar_days"]
    d = pd.Timestamp(last_date)
    return [(d + timedelta(days=step * (i + 1))).strftime("%Y-%m-%d")
            for i in range(horizon)]


def run_prediction(
    code: str,
    name: str | None,
    period: str = "daily",
    horizon: int = 7,
    context_len: int = 180,
    factors: list[dict] | None = None,
    save: bool = True,
) -> dict:
    if period not in config.PERIODS:
        raise ValueError(f"不支持的周期: {period}")
    horizon = int(horizon)
    if not (1 <= horizon <= 512):
        raise ValueError("horizon 需在 1~512 之间")
    context_len = int(context_len)
    if not (30 <= context_len <= config.MAX_CONTEXT):
        raise ValueError(f"context_len 需在 30~{config.MAX_CONTEXT} 之间")

    factor_specs = [f for f in (factors or []) if f.get("code") and f["code"] != code]

    # 1) 数据对齐（含因子 z-score）
    aligned = build_aligned_input(code, factor_specs, period, context_len)

    # 2) 推理（按配置的回退链）
    errors: list[str] = []
    result = None
    for engine in engine_candidates():
        try:
            log.info("使用引擎 %s 开始推理…", engine.name)
            result = engine.predict(
                aligned.context, horizon,
                past_only=aligned.past_only,
                return_quantiles=True, make_positive=True,
            )
            break
        except (InferenceError, Exception) as e:  # noqa: BLE001 - 逐引擎隔离
            msg = f"{engine.name}: {e}"
            log.warning("引擎失败 → 尝试下一个 (%s)", msg)
            errors.append(msg)
    if result is None:
        raise RuntimeError("所有推理引擎均失败：" + "；".join(errors))

    # 3) 组装结果
    if not name:
        name = code
    fdates = _forecast_dates(aligned.dates[-1], period, horizon)
    forecast = [round(float(v), 4) for v in result.forecast]
    last_value = float(aligned.context[-1])
    change = (result.forecast[-1] - last_value) / (abs(last_value) or 1.0) * 100

    record = {
        "stock_code": code,
        "stock_name": name,
        "period": period,
        "horizon": horizon,
        "context_len": len(aligned.dates),
        "dropped_codes": [f["code"] for f in aligned.dropped_factors],
        "factor_codes": [f["code"] for f in factor_specs
                         if f["code"] not in {d["code"] for d in aligned.dropped_factors}],
        "factor_names": aligned.factor_names,
        "inference_mode": result.mode,
        "model_version": "TimesFM-3.0",
        "historical": {"dates": aligned.dates, "values": [round(float(v), 4) for v in aligned.context]},
        "forecast": {"dates": fdates, "values": forecast},
        "quantiles": {
            "lower": [round(float(v), 4) for v in result.q_lower] if result.q_lower is not None else None,
            "upper": [round(float(v), 4) for v in result.q_upper] if result.q_upper is not None else None,
        },
        "metrics": {
            "last_value": round(last_value, 4),
            "forecast_mean": round(float(pd.Series(result.forecast).mean()), 4),
            "forecast_min": round(float(pd.Series(result.forecast).min()), 4),
            "forecast_max": round(float(pd.Series(result.forecast).max()), 4),
            "predicted_change_pct": round(float(change), 2),
        },
        "dropped_factors": aligned.dropped_factors,
        "inference_detail": result.detail,
        "engine_errors": errors,
    }
    if save:
        record["id"] = db.save_forecast(record)
    return record
