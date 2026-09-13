"""预测接口"""
import logging

from fastapi import APIRouter, HTTPException

from ..schemas import PredictRequest
from ..services.predict import run_prediction

log = logging.getLogger("api.predict")
router = APIRouter(tags=["predict"])


@router.post("/api/predict")
def predict(body: PredictRequest):
    try:
        return run_prediction(
            code=body.code,
            name=body.name,
            period=body.period,
            horizon=body.horizon,
            context_len=body.context_len,
            factors=[f.model_dump() for f in body.factors],
            save=body.save,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        log.exception("预测失败")
        raise HTTPException(502, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("预测内部错误")
        raise HTTPException(500, f"预测内部错误: {e}")
