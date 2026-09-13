"""A股数据源服务

策略：
- 主源 baostock：股票/指数全历史，ETF 历史较短（2026 年起）
- 备源 akshare(新浪)：baostock 数据不足时自动回退（ETF 全历史 / 股票备用）
- 输出统一为 DataFrame[date, open, high, low, close, volume]
"""
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from .. import config

log = logging.getLogger("datasource")

# ---------- baostock 连接管理（进程内全局，线程安全） ----------
_bs_lock = threading.RLock()
_bs_logged_in = False


def _bs_ensure_login() -> None:
    global _bs_logged_in
    if _bs_logged_in:
        return
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    _bs_logged_in = True


def _bs_reset() -> None:
    global _bs_logged_in
    try:
        import baostock as bs
        bs.logout()
    except Exception:
        pass
    _bs_logged_in = False


def _bs_query(code: str, fields: str, start: str, end: str, freq: str) -> pd.DataFrame:
    """带自动重登的 baostock K线查询"""
    import baostock as bs
    with _bs_lock:
        for attempt in (1, 2):
            try:
                _bs_ensure_login()
                adjust = "3" if freq == "d" and _is_index(code) else "2"
                rs = bs.query_history_k_data_plus(
                    code, fields, start_date=start, end_date=end,
                    frequency=freq, adjustflag=adjust,
                )
                rows = []
                while (rs.error_code == "0") and rs.next():
                    rows.append(rs.get_row_data())
                if rs.error_code != "0":
                    raise RuntimeError(f"baostock {code}: {rs.error_msg}")
                return pd.DataFrame(rows, columns=rs.fields)
            except Exception:
                _bs_reset()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")


def _is_index(code: str) -> bool:
    return code.split(".")[-1].startswith(("000", "399", "899")) and code.startswith(("sh", "sz"))


def _is_etf(code: str) -> bool:
    num = code.split(".")[-1]
    return code.startswith("sh") and num.startswith(("51", "56", "58")) or \
           code.startswith("sz") and num.startswith(("15", "16", "18"))


# ---------- 股票列表（内存缓存 + SQLite 持久化） ----------
_list_lock = threading.Lock()
_stock_list: Optional[pd.DataFrame] = None  # columns: code, name
_list_time: float = 0.0


def _load_list_from_db() -> Optional[pd.DataFrame]:
    from .. import db
    try:
        conn = db.get_conn()
        rows = conn.execute("SELECT code, name FROM stock_list").fetchall()
        if rows:
            return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        pass
    return None


def _save_list_to_db(df: pd.DataFrame) -> None:
    from .. import db
    try:
        conn = db.get_conn()
        conn.execute("DROP TABLE IF EXISTS stock_list")
        conn.execute("CREATE TABLE stock_list (code TEXT PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT OR REPLACE INTO stock_list (code, name) VALUES (?,?)",
            df.to_records(index=False).tolist(),
        )
        conn.commit()
    except Exception as e:
        log.warning("股票列表写库失败: %s", e)


def _fetch_list_baostock() -> pd.DataFrame:
    import baostock as bs
    with _bs_lock:
        for attempt in (1, 2):
            try:
                _bs_ensure_login()
                rs = bs.query_stock_basic()
                rows = []
                while (rs.error_code == "0") and rs.next():
                    rows.append(rs.get_row_data())
                df = pd.DataFrame(rows, columns=rs.fields)
                df = df[df["type"] == "1"]  # 1=股票（排除指数/ETF，避免列表过长）
                df = df[df["status"] == "1"]
                out = pd.DataFrame({
                    "code": df["code"].values,
                    "name": df["code_name"].values,
                })
                return out.reset_index(drop=True)
            except Exception:
                _bs_reset()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")


def get_stock_list() -> pd.DataFrame:
    """全部 A 股（code 如 sh.601601）。优先内存 → DB → baostock 刷新"""
    global _stock_list, _list_time
    with _list_lock:
        if _stock_list is not None and time.time() - _list_time < config.STOCK_LIST_CACHE_TTL:
            return _stock_list
        try:
            df = _fetch_list_baostock()
            if len(df):
                _stock_list, _list_time = df, time.time()
                _save_list_to_db(df)
                return df
        except Exception as e:
            log.warning("baostock 拉取股票列表失败: %s", e)
        if _stock_list is not None:
            return _stock_list
        db_df = _load_list_from_db()
        if db_df is not None:
            _stock_list, _list_time = db_df, time.time()
            return db_df
        return pd.DataFrame(columns=["code", "name"])


def search_stocks(keyword: str, limit: int = 15) -> list[dict]:
    keyword = keyword.strip().upper()
    if not keyword:
        return []
    df = get_stock_list()
    if df.empty:
        return []
    mask = df["code"].str.contains(keyword, na=False) | df["name"].str.upper().str.contains(keyword, na=False)
    hits = df[mask].head(limit)
    return hits.to_dict("records")


def get_stock_name(code: str) -> str:
    df = get_stock_list()
    if df.empty:
        return code
    hit = df[df["code"] == code]
    return hit.iloc[0]["name"] if len(hit) else code


# ---------- akshare(新浪) 备源 ----------

def _ak_stock_daily(code: str, start: str, end: str) -> pd.DataFrame:
    import akshare as ak
    mkt, num = code.split(".")
    df = ak.stock_zh_a_daily(symbol=f"{mkt}{num}", start_date=start.replace("-", ""),
                             end_date=end.replace("-", ""), adjust="qfq")
    return _ak_standardize(df)


def _ak_etf_daily(code: str) -> pd.DataFrame:
    import akshare as ak
    mkt, num = code.split(".")
    df = ak.fund_etf_hist_sina(symbol=f"{mkt}{num}")
    df = _ak_standardize(df)
    return df


def _ak_standardize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")
    return df[["date", "open", "high", "low", "close", "volume"]]


# ---------- K线统一入口 ----------

_kline_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_kline_lock = threading.Lock()


def fetch_kline(code: str, period: str = "daily",
                start: Optional[str] = None, end: Optional[str] = None,
                use_cache: bool = True) -> pd.DataFrame:
    """获取 K线（复权）。code 如 sh.601601；period: daily/weekly/monthly"""
    period_def = config.PERIODS.get(period)
    if period_def is None:
        raise ValueError(f"不支持的周期: {period}")
    end = end or datetime.now().strftime("%Y-%m-%d")
    start = start or (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

    cache_key = f"{code}|{period}|{start}|{end}"
    with _kline_lock:
        hit = _kline_cache.get(cache_key)
        if use_cache and hit and time.time() - hit[0] < config.KLINE_CACHE_TTL:
            return hit[1].copy()

    df = pd.DataFrame()
    # 1) baostock
    try:
        raw = _bs_query(code, "date,open,high,low,close,volume", start, end, period_def["freq"])
        if len(raw):
            df = raw.copy()
            df["date"] = pd.to_datetime(df["date"])
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            df = df[df["close"] > 0]
    except Exception as e:
        log.warning("baostock %s 失败: %s", code, e)

    # 2) ETF 历史不足（baostock 仅 2026 年起）→ 新浪补全
    margin = pd.Timestamp(start) + pd.Timedelta(days=45)
    if _is_etf(code) and (df.empty or df["date"].min() > margin):
        try:
            ak_df = _ak_etf_daily(code)
            ak_df = ak_df[(ak_df["date"] >= start) & (ak_df["date"] <= end)]
            if len(ak_df) > len(df):
                df = ak_df
        except Exception as e:
            log.warning("akshare ETF %s 失败: %s", code, e)

    # 3) 股票完全失败 → 新浪股票
    if df.empty and not _is_index(code) and not _is_etf(code):
        try:
            df = _ak_stock_daily(code, start, end)
        except Exception as e:
            log.warning("akshare 股票 %s 失败: %s", code, e)

    df = df.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)

    with _kline_lock:
        _kline_cache[cache_key] = (time.time(), df.copy())
        if len(_kline_cache) > 500:
            _kline_cache.pop(next(iter(_kline_cache)))
    return df


# ---------- 交易日历 ----------

_trade_dates_cache: Optional[tuple[str, set[str]]] = None  # (year, dates)


def get_trade_dates(year: Optional[int] = None) -> set[str]:
    """返回某年 A 股交易日集合（YYYY-MM-DD）。失败时退化为工作日。"""
    global _trade_dates_cache
    year = year or datetime.now().year
    with _bs_lock:
        try:
            if _trade_dates_cache and _trade_dates_cache[0] == str(year):
                return _trade_dates_cache[1]
            import baostock as bs
            _bs_ensure_login()
            rs = bs.query_trade_dates(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
            dates = set()
            while (rs.error_code == "0") and rs.next():
                if rs.get_row_data()[1] == "1":
                    dates.add(rs.get_row_data()[0])
            # 跨年预测需要下一年日历，一并取
            rs2 = bs.query_trade_dates(start_date=f"{year + 1}-01-01", end_date=f"{year + 1}-12-31")
            while (rs2.error_code == "0") and rs2.next():
                if rs2.get_row_data()[1] == "1":
                    dates.add(rs2.get_row_data()[0])
            if dates:
                _trade_dates_cache = (str(year), dates)
            return dates
        except Exception as e:
            log.warning("交易日历获取失败: %s", e)
            return set()


def next_trade_dates(last_date: str, n: int) -> list[str]:
    """给定最后交易日的次日起 n 个未来交易日"""
    d = pd.Timestamp(last_date)
    year = d.year
    dates = get_trade_dates(year)
    if not dates or max(dates) <= last_date:
        year += 1
        dates = dates | get_trade_dates(year)
    future = sorted(x for x in dates if x > last_date)
    if len(future) >= n:
        return future[:n]
    # 日历缺失兜底：跳过周末顺延
    out = list(future)
    cur = pd.Timestamp(future[-1]) if future else d
    while len(out) < n:
        cur += pd.Timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y-%m-%d"))
    return out[:n]


# ---------- 热门股票 ----------

HOT_STOCKS = [
    {"code": "sh.601601", "name": "中国太保"},
    {"code": "sh.600900", "name": "长江电力"},
    {"code": "sh.601398", "name": "工商银行"},
    {"code": "sh.600887", "name": "伊利股份"},
    {"code": "sh.600519", "name": "贵州茅台"},
    {"code": "sh.601318", "name": "中国平安"},
    {"code": "sz.300750", "name": "宁德时代"},
    {"code": "sz.002594", "name": "比亚迪"},
    {"code": "sh.600036", "name": "招商银行"},
    {"code": "sz.000858", "name": "五粮液"},
]
