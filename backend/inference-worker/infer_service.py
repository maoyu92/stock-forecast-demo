#!/usr/bin/env python
"""TimesFM 3.0 常驻推理 worker（部署在 GPU 服务器上）

由 FastAPI 后端经 SSH 启动：  .venv/bin/python -u infer_service.py
协议（JSON Lines，stdin → stdout）：
  请求: {"id": N, "context": [...], "horizon": H,
         "past_only": [[...]]|null, "return_quantiles": bool, "make_positive": bool}
  响应: {"id": N, "ok": true, "forecast": [...], "quantiles": [[9 x H]]|null}
        {"id": N, "ok": false, "error": "..."}

约束（依据 TimesFM3 使用说明）：
- 仅依赖 numpy + timesfm 包（服务器无 pandas / 无外网 PyPI）
- past_only_covariates 形状必须 (V, ctx_len)，与 context 等长
- 模型整个进程只加载一次，加载完成后输出 READY
- 定期 try_gc 防显存碎片
"""
import json
import sys
import traceback

import numpy as np


def load_model():
    try:
        from timesfm import TimesFM3Forecaster
    except ImportError:
        from timesfm3 import TimesFM3Forecaster
    return TimesFM3Forecaster.from_pretrained("google/timesfm-3.0-pytorch")


def respond(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    print("loading model...", flush=True)
    model = load_model()
    print("READY", flush=True)

    call_count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            respond({"id": -1, "ok": False, "error": f"bad json: {e}"})
            continue

        rid = req.get("id", -1)
        try:
            context = np.asarray(req["context"], dtype=np.float32)
            if context.ndim != 1:
                raise ValueError(f"context 必须是一维序列，收到 shape={context.shape}")
            horizon = int(req["horizon"])
            if horizon <= 0 or horizon > 512:
                raise ValueError(f"horizon 非法: {horizon}")
            po = req.get("past_only")
            po_arr = None
            if po:
                po_arr = np.asarray(po, dtype=np.float32)
                if po_arr.shape[1] != context.shape[0]:
                    raise ValueError(
                        f"past_only 宽度 {po_arr.shape[1]} 必须等于 context 长度 {context.shape[0]}")
            out = model.predict(
                context,
                horizon=horizon,
                past_only_covariates=po_arr,
                return_quantiles=bool(req.get("return_quantiles", True)),
                make_positive=bool(req.get("make_positive", True)),
            )
            quantiles = None
            if getattr(out, "quantiles", None) is not None:
                quantiles = np.asarray(out.quantiles, dtype=np.float64).tolist()
            respond({
                "id": rid, "ok": True,
                "forecast": np.asarray(out.forecast, dtype=np.float64).tolist(),
                "quantiles": quantiles,
            })
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            respond({"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"})

        call_count += 1
        if call_count % 50 == 0:
            try:
                from timesfm3.timesfm3_forecaster import try_gc
                try_gc()
            except Exception:
                import gc
                gc.collect()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
