"""自选分组接口"""
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..services import quotes

router = APIRouter(prefix="/api/watch", tags=["watch"])

INDEX_CODES = ["sh000001", "sz399001", "sz399006", "sh000688", "sh000300"]


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)


class GroupRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)


class ItemCreate(BaseModel):
    code: str = Field(..., description="如 sh600000")
    name: str = Field("", description="股票名称，缺省自动查询")


@router.get("/groups")
def groups(with_quotes: bool = True):
    """全部分组及成员（with_quotes=True 时合并实时快照与涨跌幅排序数据）"""
    gs = db.list_watch_groups()
    if with_quotes:
        codes = sorted({it["code"] for g in gs for it in g["items"]} | set(INDEX_CODES))
        spot = quotes.spot(codes)
        for g in gs:
            for it in g["items"]:
                s = spot.get(it["code"])
                if s:
                    it["price"] = s["price"]
                    it["pct"] = s["pct"]
                else:
                    it["price"] = None
                    it["pct"] = None
    return {"groups": gs, "indexes": _index_quotes()}


def _index_quotes() -> list[dict]:
    spot = quotes.spot(INDEX_CODES)
    out = []
    for c in INDEX_CODES:
        s = spot.get(c)
        if s:
            out.append({"code": c, "name": s["name"], "price": s["price"], "pct": s["pct"]})
    return out


@router.post("/groups")
def add_group(body: GroupCreate):
    try:
        gid = db.create_watch_group(body.name.strip())
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"分组已存在: {body.name}")
    return {"id": gid}


@router.put("/groups/{group_id}")
def rename_group(group_id: int, body: GroupRename):
    try:
        if not db.rename_watch_group(group_id, body.name.strip()):
            raise HTTPException(404, "分组不存在")
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"分组已存在: {body.name}")
    return {"ok": True}


@router.delete("/groups/{group_id}")
def delete_group(group_id: int):
    if not db.delete_watch_group(group_id):
        raise HTTPException(404, "分组不存在")
    return {"ok": True}


@router.post("/groups/{group_id}/items")
def add_item(group_id: int, body: ItemCreate):
    name = body.name or quotes.spot([body.code]).get(body.code, {}).get("name", "")
    try:
        item_id = db.add_watch_item(group_id, body.code, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": item_id, "name": name}


@router.delete("/items/{item_id}")
def remove_item(item_id: int):
    if not db.remove_watch_item(item_id):
        raise HTTPException(404, "条目不存在")
    return {"ok": True}
