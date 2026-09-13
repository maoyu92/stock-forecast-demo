"""系统状态接口"""
from fastapi import APIRouter

from .. import config
from ..services.inference import engine_status

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    return {"status": "ok", "inference": engine_status()}
