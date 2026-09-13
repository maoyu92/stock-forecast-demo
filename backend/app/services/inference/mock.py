"""模拟引擎：无 GPU / 服务器不可达时的回退，输出可复现的"合理"走势

并非真实 TimesFM 结果，前端会明确标注【模拟】。
"""
import hashlib

import numpy as np

from .base import BaseEngine, InferenceResult


class MockEngine(BaseEngine):
    name = "mock"

    def predict(self, context, horizon, past_only=None,
                return_quantiles=True, make_positive=True) -> InferenceResult:
        ctx = np.asarray(context, dtype=np.float64)
        last = float(ctx[-1])

        # 以数据末尾日期+长度做种子，保证同样输入输出可复现
        seed_src = f"{len(ctx)}:{last:.6f}:{ctx[:3].mean():.6f}"
        seed = int(hashlib.md5(seed_src.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)

        # 近期收益率的阻尼外推 + 温和噪声
        rets = np.diff(ctx[-21:]) / np.where(ctx[-21:-1] == 0, 1, ctx[-21:-1])
        vol = float(np.std(rets)) if len(rets) > 2 else 0.01
        vol = min(max(vol, 0.003), 0.06)
        drift = float(np.mean(rets)) * 0.4

        steps = np.arange(1, horizon + 1)
        decay = 0.92 ** steps
        noise = rng.normal(0, vol, horizon)
        path = last * np.cumprod(1 + drift * decay + noise)
        forecast = path.astype(np.float64)

        q_lower = q_upper = None
        if return_quantiles:
            spread = last * vol * 0.84 * np.sqrt(steps)
            q_lower = (forecast - spread).clip(min=0)
            q_upper = forecast + spread

        return InferenceResult(
            forecast=forecast,
            q_lower=q_lower, q_upper=q_upper,
            mode="mock",
            detail="模拟引擎（非真实 TimesFM 推理）",
        )

    def status(self) -> dict:
        return {"available": True, "name": "mock",
                "detail": "模拟引擎：历史动量外推，仅供流程演示"}
