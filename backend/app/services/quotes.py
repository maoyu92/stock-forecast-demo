"""实时行情服务 —— 腾讯快照(主) + 新浪快照/分钟线(备/分时)

- spot(): 批量实时快照（指数/个股/ETF 通用），供自选列表与指数条轮询
- intraday(): 当日分时（新浪 5 分钟K聚合，含均价线）
- kline(): 任意标的 K线（个股走本地仓库，指数/ETF 走新浪日K），周/月K 重采样
- kline_full(): K线 + 常用技术指标序列（MA/MACD/KDJ/RSI/BOLL/VOL），供图表页
"""
import logging
import threading
import time

import pandas as pd
import requests

log = logging.getLogger("quotes")

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.sina.com.cn"}

# 快照进程内缓存（防轮询打爆）
_spot_lock = threading.Lock()
_spot_cache: dict[str, tuple[float, dict]] = {}
_SPOT_TTL = 5.0


def _http_get(url: str, timeout: int = 8) -> str:
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = "gbk"
    return r.text


# ---------- 实时快照（腾讯 qt） ----------

def spot(codes: list[str]) -> dict[str, dict]:
    """批量实时快照。codes 如 ['sh600000','sz000001','sh000001']。
    返回 {code: {name, price, prev_close, open, high, low, volume(手), amount(元),
                 pct, time}}，失败的代码不在结果里。"""
    now = time.time()
    out: dict[str, dict] = {}
    pending: list[str] = []
    with _spot_lock:
        for c in codes:
            hit = _spot_cache.get(c)
            if hit and now - hit[0] < _SPOT_TTL:
                out[c] = hit[1]
            else:
                pending.append(c)

    for i in range(0, len(pending), 50):
        batch = pending[i:i + 50]
        try:
            text = _http_get("https://qt.gtimg.cn/q=" + ",".join(batch))
            for line in text.split(";"):
                line = line.strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                code = key.split("_", 1)[-1].strip().strip('"')
                f = val.strip('"').split("~")
                if len(f) < 38 or not f[3]:
                    continue
                try:
                    item = {
                        "name": f[1],
                        "price": float(f[3]),
                        "prev_close": float(f[4]) if f[4] else None,
                        "open": float(f[5]) if f[5] else None,
                        "volume": float(f[6]) if f[6] else 0.0,        # 手
                        "pct": float(f[32]) if f[32] else 0.0,
                        "high": float(f[33]) if f[33] else None,
                        "low": float(f[34]) if f[34] else None,
                        "amount": float(f[37]) * 1e4 if f[37] else 0.0,  # 万→元
                        "time": f[30],
                    }
                    if f[37] and "/" in f[35]:
                        pass  # f[35] 为组合串，已用 f[37]
                    out[code] = item
                    with _spot_lock:
                        _spot_cache[code] = (now, item)
                except (TypeError, ValueError):
                    continue
        except Exception as e:  # noqa: BLE001 —— 失败的批次跳过
            log.warning("腾讯快照批次失败: %s", e)

    # 腾讯缺的用新浪补（少数网络环境差异）
    miss = [c for c in pending if c not in out]
    if miss:
        try:
            text = _http_get("https://hq.sinajs.cn/list=" + ",".join(miss))
            for line in text.splitlines():
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                code = key.split("=", 1)[-1].replace("hq_str_", "").strip()
                f2 = val.strip('"').split(",")
                if len(f2) < 32:
                    continue
                try:
                    item = {
                        "name": f2[0], "price": float(f2[3]),
                        "prev_close": float(f2[2]) or None, "open": float(f2[1]) or None,
                        "high": float(f2[4]) or None, "low": float(f2[5]) or None,
                        "volume": float(f2[8]) if f2[8] else 0.0,
                        "amount": float(f2[9]) if f2[9] else 0.0,
                        "pct": (float(f2[3]) / float(f2[2]) - 1) * 100 if float(f2[2]) else 0.0,
                        "time": f2[-2] + " " + f2[-1] if len(f2) > 31 else "",
                    }
                    out[code] = item
                    with _spot_lock:
                        _spot_cache[code] = (now, item)
                except (TypeError, ValueError, IndexError):
                    continue
        except Exception as e:  # noqa: BLE001
            log.warning("新浪快照备源失败: %s", e)
    return out


# ---------- 分时（新浪 5 分钟K聚合当日） ----------

def _sina_minute_kline(symbol: str, scale: int = 5, datalen: int = 64) -> pd.DataFrame:
    """新浪分钟K。scale: 5/15/30/60/240(日)，datalen 上限 1975"""
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/x=/CN_MarketDataService.getKLineData"
           f"?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}")
    text = _http_get(url)
    s = text.find("=(")
    e = text.rfind(")")
    if s < 0 or e < 0:
        raise RuntimeError("新浪分钟线返回格式异常")
    import json
    data = json.loads(text[s + 2:e])
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df = df.rename(columns={"day": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def intraday(code: str) -> dict:
    """当日分时：5分钟K → (time, price, avg, volume)。含今开作首值锚点。"""
    df = _sina_minute_kline(code, scale=5, datalen=64)
    if df.empty:
        raise RuntimeError(f"{code} 无分时数据")
    today = df["date"].max().strftime("%Y-%m-%d")
    df = df[df["date"].dt.strftime("%Y-%m-%d") == today].reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"{code} 今日暂无分时数据")
    typical = (df["high"] + df["low"] + df["close"]) / 3
    avg = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
    return {
        "code": code,
        "date": today,
        "times": df["date"].dt.strftime("%H:%M").tolist(),
        "prices": df["close"].round(3).tolist(),
        "avgs": avg.round(3).ffill().round(3).tolist(),
        "volumes": df["volume"].fillna(0).astype(float).tolist(),
        "prev_close": float(df["open"].iloc[0]),
    }


# ---------- K线（个股本地仓库 / 指数·ETF 新浪） + 周/月重采样 ----------

def _resample(df: pd.DataFrame, period: str) -> pd.DataFrame:
    rule = {"weekly": "W-FRI", "monthly": "ME"}.get(period)
    if not rule:
        return df
    df = df.set_index("date")
    agg_map = {"open": "first", "high": "max", "low": "min",
               "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg_map["amount"] = "sum"
    agg = df.resample(rule).agg(agg_map).dropna(subset=["close"])
    return agg.reset_index()


def kline(code: str, period: str = "daily", bars: int = 250) -> pd.DataFrame:
    """任意标的日/周/月K。个股优先本地仓库（含成交额），指数/ETF/缺数据走新浪。"""
    from . import histstore

    df = pd.DataFrame()
    if code.startswith(("sh6", "sz0", "sz3")):  # 个股：本地仓库（快、全、含额）
        n_bars = bars if period == "daily" else max(bars * 6, 400)
        df = histstore.read_kline(code, n_bars)
    if df.empty:  # 指数/ETF 或本地无数据 → 新浪日K
        try:
            df = _sina_minute_kline(code, scale=240, datalen=min(bars * 8, 1975) if period != "daily" else min(bars + 20, 1975))
        except Exception as e:  # noqa: BLE001
            log.warning("新浪日K失败 %s: %s", code, e)
    if df.empty:
        return df
    if period != "daily":
        df = _resample(df, period)
    df = df.tail(bars).reset_index(drop=True)
    if "amount" not in df:
        df["amount"] = df["close"] * df["volume"]
    return df


# ---------- 技术指标序列（图表页副图） ----------

def kline_full(code: str, period: str = "daily", bars: int = 250) -> dict:
    """K线 + MA/MACD/KDJ/RSI/BOLL/VOL 指标序列（None 表示 NaN）"""
    from .screener import indicators as ind

    df = kline(code, period, bars)
    if df.empty:
        raise RuntimeError(f"{code} 无K线数据")
    c = df["close"].astype(float)

    def series(s: pd.Series, nd: int = 2) -> list:
        return [None if pd.isna(v) else round(float(v), nd) for v in s]

    out = {
        "code": code,
        "dates": df["date"].dt.strftime("%Y-%m-%d %H:%M".strip()).tolist(),
        "open": series(df["open"], 3), "high": series(df["high"], 3),
        "low": series(df["low"], 3), "close": series(df["close"], 3),
        "volume": series(df["volume"].astype(float), 0),
        "amount": series(df["amount"].astype(float), 0),
        "ma5": series(ind.ma(c, 5)), "ma10": series(ind.ma(c, 10)),
        "ma20": series(ind.ma(c, 20)), "ma60": series(ind.ma(c, 60)),
    }
    dif, dea, mc = ind.macd(c)
    out["dif"], out["dea"], out["macd"] = series(dif, 3), series(dea, 3), series(mc, 3)

    low, high = df["low"].astype(float), df["high"].astype(float)
    rsv = (c - low.rolling(9).min()) / (high.rolling(9).max() - low.rolling(9).min() + 1e-9) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    out["kdj_k"], out["kdj_d"], out["kdj_j"] = series(k), series(d), series(3 * k - 2 * d)

    lc = c.shift(1)
    up = (c - lc).clip(lower=0).ewm(alpha=1 / 6, adjust=False).mean()
    dn = (c - lc).abs().ewm(alpha=1 / 6, adjust=False).mean()
    out["rsi6"] = series(up / (dn + 1e-9) * 100)

    mid = ind.ma(c, 20)
    std = c.rolling(20).std()
    out["boll_mid"], out["boll_up"] = series(mid), series(mid + 2 * std)
    out["boll_low"] = series(mid - 2 * std)
    return out
