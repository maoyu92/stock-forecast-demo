"""多因子：内置预设 + 用户自定义组合"""
from fastapi import APIRouter, HTTPException

from .. import db
from ..schemas import FactorGroupCreate
from ..services import datasource, industry
from ..services.presets import BUILTIN_PRESETS, ETF_QUICK_PICKS, find_preset_by_code

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("/auto")
def auto_factors(code: str):
    """选股后自动关联多因子：内置预设 / 同板块龙头 + 沪深300"""
    return industry.auto_factors(code)


@router.get("/presets")
def presets():
    return {"presets": BUILTIN_PRESETS, "etf_quick_picks": ETF_QUICK_PICKS}


@router.get("/preset-of/{code}")
def preset_of(code: str):
    p = find_preset_by_code(code)
    return p or {"target": {"code": code, "name": datasource.get_stock_name(code)}, "factors": []}


@router.get("/groups")
def list_groups():
    return {"groups": db.list_factor_groups()}


@router.post("/groups")
def create_group(body: FactorGroupCreate):
    name = body.target_name or datasource.get_stock_name(body.target_code)
    factors = [f.model_dump() for f in body.factors]
    gid = db.save_factor_group(body.name, body.target_code, name, factors)
    return {"id": gid}


@router.delete("/groups/{group_id}")
def delete_group(group_id: int):
    if not db.delete_factor_group(group_id):
        raise HTTPException(404, "组合不存在")
    return {"ok": True}
