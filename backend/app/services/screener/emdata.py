"""东方财富行情直连 —— 全市场快照 + 个股资金流

东财 push2 主站在部分网络环境下会重置连接，因此统一走"主机回退链"：
快照 push2delay(延时镜像) → push2；资金流 push2his → push2delay。
快照接口单页上限 100 条，全市场约 60 页，用小线程池并发拉取后合并。
"""
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

from ... import config

log = logging.getLogger("screener.emdata")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}
_PAGE_SIZE = 100  # 东财 clist 单页硬上限

_SNAPSHOT_HOSTS = ["https://push2delay.eastmoney.com", "https://push2.eastmoney.com"]
_FLOW_HOSTS = ["https://push2his.eastmoney.com", "https://push2delay.eastmoney.com"]
# 全市场资金流聚合排行：push2delay 可用（push2his 仅个股日K接口）
_FLOW_RANK_HOSTS = ["https://push2delay.eastmoney.com", "https://push2.eastmoney.com"]

# 主机健康记忆：失败后该时长内不再首选该主机（秒）
_HOST_FAIL_TTL = 600
_host_fail_at: dict[str, float] = {}

# clist 字段：f12代码 f14名称 f2最新价 f3涨跌幅 f5成交量(手) f6成交额(元)
#             f8换手率 f10量比 f15高 f16低 f17开 f18昨收
_SNAP_FIELDS = "f12,f14,f2,f3,f5,f6,f8,f10,f15,f16,f17,f18"
_SNAP_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"  # 沪深主板+创业板+科创板+北证


def _em_get(path: str, params: dict, hosts: list[str], timeout: int = 15) -> dict:
    """依次尝试主机回退链请求东财接口，全部失败抛 RuntimeError。

    带"主机健康记忆"：最近失败过的主机在 _HOST_FAIL_TTL 秒内排到队尾，
    避免每只股票都先撞一次被墙的主机（拖慢速度 + 日志噪音）。
    """
    now = time.time()
    ordered = sorted(hosts, key=lambda h: _host_fail_at.get(h, 0))
    tried = [h for h in ordered if now - _host_fail_at.get(h, 0) > _HOST_FAIL_TTL] or ordered
    last_err: Exception | None = None
    for host in tried:
        try:
            r = requests.get(host + path, params=params, headers=_HEADERS, timeout=timeout)
            r.raise_for_status()
            _host_fail_at.pop(host, None)
            return r.json()
        except Exception as e:  # noqa: BLE001 —— 逐主机降级
            _host_fail_at[host] = time.time()
            last_err = e
            log.warning("东财接口 %s%s 失败: %s", host, path, e)
    raise RuntimeError(f"东方财富接口不可用: {last_err}")


def _to_num(v) -> float:
    """'-' / 缺失 → NaN，其余转 float"""
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


# ---------- 全市场快照 ----------

_snap_lock = threading.Lock()
_snap_cache: Optional[pd.DataFrame] = None
_snap_time: float = 0.0


def _fetch_page(pn: int) -> list[dict]:
    data = _em_get(
        "/api/qt/clist/get",
        {"pn": pn, "pz": _PAGE_SIZE, "po": 1, "np": 1, "fltt": 2, "invt": 2,
         "fid": "f3", "fs": _SNAP_FS, "fields": _SNAP_FIELDS},
        _SNAPSHOT_HOSTS,
    )
    diff = (data.get("data") or {}).get("diff")
    if not diff:
        return []
    return list(diff.values()) if isinstance(diff, dict) else diff


def get_snapshot(force: bool = False) -> tuple[pd.DataFrame, str]:
    """全市场 A 股快照（含实时价/涨跌幅/量比/换手率）。

    返回 (DataFrame[code6, name, price, pct, volume, amount, turnover, volume_ratio],
          快照时间 ISO 文本)。带进程内缓存（TTL 见 config）。
    """
    global _snap_cache, _snap_time
    with _snap_lock:
        if (not force and _snap_cache is not None
                and time.time() - _snap_time < config.SCREEN_SNAPSHOT_TTL):
            return _snap_cache.copy(), datetime.fromtimestamp(_snap_time).isoformat(timespec="seconds")

    first = _fetch_page(1)
    total = len(first)
    # 首页若被限流会拿到空数据，直接报错交由上层提示
    if total == 0:
        raise RuntimeError("东方财富快照返回空数据，可能被限流，请稍后重试")
    pages = [first]

    def _task(pn: int) -> list[dict]:
        for _ in range(2):  # 单页重试一次
            try:
                return _fetch_page(pn)
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        return []

    with ThreadPoolExecutor(max_workers=6) as pool:
        for rows in pool.map(_task, range(2, math.ceil(6000 / _PAGE_SIZE) + 1)):
            pages.append(rows)

    rows = [r for page in pages for r in page]
    df = pd.DataFrame([
        {
            "code6": str(r.get("f12", "")),
            "name": str(r.get("f14", "")),
            "price": _to_num(r.get("f2")),
            "pct": _to_num(r.get("f3")),
            "volume": _to_num(r.get("f5")),
            "amount": _to_num(r.get("f6")),
            "turnover": _to_num(r.get("f8")),
            "volume_ratio": _to_num(r.get("f10")),
        }
        for r in rows if r.get("f12")
    ]).drop_duplicates(subset="code6").reset_index(drop=True)

    if df.empty:
        raise RuntimeError("东方财富快照解析失败")

    _snap_cache, _snap_time = df, time.time()
    return df.copy(), datetime.fromtimestamp(_snap_time).isoformat(timespec="seconds")


def to_bs_code(code6: str) -> str:
    """6 位代码 → baostock 代码（60/68 开头沪市，其余深市/北证按 sz 处理交由过滤规则）"""
    return ("sh." if code6.startswith("6") else "sz.") + code6


# ---------- 全市场资金流排行（主力净流入，东财聚合接口） ----------

def fund_flow_rank(top_n: int = 100) -> pd.DataFrame:
    """按主力净流入(f62)降序的全市场排行（聚合接口，每页100条，取前 top_n）。

    返回 DataFrame[code6, name, price, pct, volume(手), amount(元), turnover(%),
                  main_net(元), super_net(元), big_net(元), main_pct(%)]
    """
    rows: list[dict] = []
    pages = max(1, math.ceil(top_n / _PAGE_SIZE))
    for pn in range(1, pages + 1):
        data = _em_get(
            "/api/qt/clist/get",
            {"pn": pn, "pz": _PAGE_SIZE, "po": 1, "np": 1, "fltt": 2, "invt": 2,
             "fid": "f62", "fs": _SNAP_FS,
             "fields": "f12,f14,f2,f3,f5,f6,f8,f62,f66,f72,f184"},
            _FLOW_RANK_HOSTS,
        )
        diff = (data.get("data") or {}).get("diff") or []
        it = diff.values() if isinstance(diff, dict) else diff
        rows.extend(it)

    df = pd.DataFrame([
        {
            "code6": str(r.get("f12", "")),
            "name": str(r.get("f14", "")),
            "price": _to_num(r.get("f2")),
            "pct": _to_num(r.get("f3")),
            "volume": _to_num(r.get("f5")),
            "amount": _to_num(r.get("f6")),
            "turnover": _to_num(r.get("f8")),
            "main_net": _to_num(r.get("f62")),
            "super_net": _to_num(r.get("f66")),
            "big_net": _to_num(r.get("f72")),
            "main_pct": _to_num(r.get("f184")),
        }
        for r in rows if r.get("f12")
    ]).drop_duplicates(subset="code6").head(top_n).reset_index(drop=True)
    if df.empty:
        raise RuntimeError("东财资金流排行返回空数据，可能被限流，请稍后重试")
    return df


# ---------- 个股资金流（日线级主力净流入） ----------

def fetch_fund_flow(code6: str, days: int = 3) -> Optional[list[dict]]:
    """近 N 日主力资金流（东财 fflow 日K）。

    返回 [{"date", "main_net"(元)}...] 或 None（接口不可用/无数据时由上层降级）。
    """
    secid = ("1." if code6.startswith("6") else "0.") + code6
    try:
        data = _em_get(
            "/api/qt/stock/fflow/daykline/get",
            {"lmt": str(days), "klt": "101", "fields1": "f1,f2,f3,f7",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
             "ut": "b2884a393a59ad64002292a3e90d46a5", "secid": secid},
            _FLOW_HOSTS,
        )
        klines = (data.get("data") or {}).get("klines") or []
        out = []
        for line in klines[-days:]:
            parts = line.split(",")
            # f51日期, f52主力净流入额, f53小单, f54中单, f55大单, f56超大单
            out.append({"date": parts[0], "main_net": _to_num(parts[1])})
        return out or None
    except Exception as e:  # noqa: BLE001 —— 资金流失败不阻断选股
        log.warning("资金流获取失败 %s: %s", code6, e)
        return None
