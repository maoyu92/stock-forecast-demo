"""推理引擎基类与结果结构"""
from dataclasses import dataclass

import numpy as np


@dataclass
class InferenceResult:
    forecast: np.ndarray          # (horizon,) 中位数预测
    q_lower: np.ndarray | None    # (horizon,) 下分位（如 0.2）
    q_upper: np.ndarray | None    # (horizon,) 上分位（如 0.8）
    mode: str                     # remote / local / mock
    detail: str = ""              # 设备/服务器等信息


class InferenceError(RuntimeError):
    """推理失败（引擎不可用或执行出错）"""


def extract_band(quantiles, low_idx: int, high_idx: int):
    """从 9 分位矩阵提取置信带，自动兼容 (9, H) 与 (H, 9) 两种方向"""
    q = np.asarray(quantiles, dtype=np.float64)
    if q.ndim != 2:
        return None, None
    if q.shape[1] == 9:      # (horizon, 9) —— timesfm 3.0.1 本地包
        return q[:, low_idx], q[:, high_idx]
    if q.shape[0] == 9:      # (9, horizon) —— 部分服务器版本
        return q[low_idx], q[high_idx]
    return None, None


class BaseEngine:
    name = "base"

    def predict(
        self,
        context: np.ndarray,
        horizon: int,
        past_only: np.ndarray | None = None,
        return_quantiles: bool = True,
        make_positive: bool = True,
    ) -> InferenceResult:
        raise NotImplementedError

    def status(self) -> dict:
        return {"available": False, "name": self.name}
