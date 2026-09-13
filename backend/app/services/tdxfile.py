"""通达信本地日K文件（vipdoc）读取器 —— 可选数据源

通达信 PC 客户端把日K存在  <vipdoc>/sh/lday/sh600000.day  这类二进制文件里，
每条记录 32 字节，无加密：

    offset 0   u32  日期 YYYYMMDD
    offset 4   u32  开盘价 ×100
    offset 8   u32  最高价 ×100
    offset 12  u32  最低价 ×100
    offset 16  u32  收盘价 ×100
    offset 20  f32  成交额（元）
    offset 24  u32  成交量（股）
    offset 28  u32  保留字段

注意：通达信本地数据为**不复权**价格，跨除权日的均线会跳变；
本仓库主源为 baostock 前复权，通达信文件仅作为补充/离线来源。
"""
import logging
import struct
from pathlib import Path

import pandas as pd

from .. import config

log = logging.getLogger("tdxfile")

_RECORD = struct.Struct("<IIIIIfII")  # date, open, high, low, close, amount, vol, reserved


def vipdoc_root() -> Path | None:
    p = config.TDX_VIPDOC_PATH.strip()
    return Path(p) if p else None


def read_day_file(path: Path) -> pd.DataFrame:
    """解析单个 .day 文件 → DataFrame[date, open, high, low, close, volume, amount]"""
    raw = path.read_bytes()
    n = len(raw) // _RECORD.size
    rows = [_RECORD.unpack_from(raw, i * _RECORD.size) for i in range(n)]
    df = pd.DataFrame(rows, columns=[
        "date", "open", "high", "low", "close", "amount", "volume", "reserved"])
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] / 100.0
    df["amount"] = df["amount"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]


def read_stock(code: str) -> pd.DataFrame | None:
    """按 baostock 代码（sh.600000）读通达信本地日K；文件不存在返回 None"""
    root = vipdoc_root()
    if root is None:
        return None
    mkt, num = code.split(".")
    path = root / mkt / "lday" / f"{mkt}{num}.day"
    if not path.exists():
        return None
    try:
        return read_day_file(path)
    except Exception as e:  # noqa: BLE001
        log.warning("解析通达信文件失败 %s: %s", path, e)
        return None
