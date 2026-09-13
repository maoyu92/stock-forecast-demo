"""本地 TimesFM 引擎：直接在本进程加载模型（需 pip install timesfm + torch）"""
import threading
import time

import numpy as np

from ... import config
from .base import BaseEngine, InferenceError, InferenceResult, extract_band

_load_lock = threading.Lock()
_predict_lock = threading.Lock()
_model = None
_model_device = ""


def _import_forecaster():
    try:
        from timesfm import TimesFM3Forecaster  # timesfm>=3.0
        return TimesFM3Forecaster
    except ImportError:
        pass
    try:
        from timesfm3 import TimesFM3Forecaster  # 部分环境包名为 timesfm3
        return TimesFM3Forecaster
    except ImportError:
        return None


def is_importable() -> bool:
    return _import_forecaster() is not None


def _get_model():
    global _model, _model_device
    if _model is not None:
        return _model
    with _load_lock:
        if _model is not None:
            return _model
        cls = _import_forecaster()
        if cls is None:
            raise InferenceError("本地未安装 timesfm（pip install 'timesfm[torch]'）")
        t0 = time.time()
        _model = cls.from_pretrained(config.TIMESFM_MODEL_ID)
        _model_device = str(getattr(_model, "device", "auto"))
        print(f"[local-timesfm] 模型加载完成 {time.time() - t0:.1f}s, device={_model_device}")
    return _model


class LocalTimesFMEngine(BaseEngine):
    name = "local"

    def predict(self, context, horizon, past_only=None,
                return_quantiles=True, make_positive=True) -> InferenceResult:
        model = _get_model()
        ctx = np.asarray(context, dtype=np.float32)
        po = np.asarray(past_only, dtype=np.float32) if past_only is not None else None
        with _predict_lock:  # 模型推理非线程安全
            out = model.predict(
                ctx, horizon=horizon,
                past_only_covariates=po,
                return_quantiles=return_quantiles,
                make_positive=make_positive,
            )
        forecast = np.asarray(out.forecast, dtype=np.float64)
        q_lower = q_upper = None
        if return_quantiles and getattr(out, "quantiles", None) is not None:
            q_lower, q_upper = extract_band(out.quantiles,
                                            config.QUANTILE_LOW_IDX, config.QUANTILE_HIGH_IDX)
        return InferenceResult(forecast=forecast, q_lower=q_lower, q_upper=q_upper,
                               mode="local", detail=f"本地推理 device={_model_device}")

    def status(self) -> dict:
        ok = is_importable()
        return {"available": ok, "name": "local",
                "detail": "timesfm 已安装，可本地推理" if ok
                else "未安装 timesfm（需要 torch）"}
