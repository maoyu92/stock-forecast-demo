"""A股股票数据获取模块 - baostock 主数据源 + akshare 备用"""
import pandas as pd
import baostock as bs
from typing import Optional, List, Dict
import time

# baostock 股票列表缓存
_stock_list_cache: Optional[pd.DataFrame] = None
_cache_time: float = 0
CACHE_TTL = 3600  # 缓存1小时


def _bs_login():
    """baostock 登录"""
    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    return lg


def _bs_logout():
    """baostock 登出"""
    bs.logout()


def get_stock_list() -> pd.DataFrame:
    """获取A股股票列表（沪深全部）"""
    global _stock_list_cache, _cache_time

    if _stock_list_cache is not None and (time.time() - _cache_time) < CACHE_TTL:
        return _stock_list_cache

    try:
        _bs_login()
        # 获取所有 A 股股票
        rs = bs.query_stock_basic()
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        df = pd.DataFrame(data_list, columns=rs.fields)
        # 只保留 A 股（sh/sz 开头，且状态为上市）
        df = df[df['code'].str.match(r'^(sh|sz)\.\d{6}$')]
        df = df[df['status'] == '1']  # 1=上市

        # 提取纯代码和名称
        df = df[['code', 'code_name']].copy()
        df['code'] = df['code'].str.replace(r'^(sh|sz)\.', '', regex=True)
        df.columns = ['code', 'name']

        _stock_list_cache = df
        _cache_time = time.time()
        _bs_logout()
        return df

    except Exception as e:
        print(f"[baostock] 获取股票列表失败: {e}")
        try:
            _bs_logout()
        except:
            pass
        return pd.DataFrame(columns=['code', 'name'])


def search_stocks(keyword: str, limit: int = 20) -> List[Dict[str, str]]:
    """搜索股票（支持代码或名称模糊匹配）"""
    df = get_stock_list()
    if df.empty:
        return []

    keyword = keyword.strip().upper()
    mask = df['code'].str.contains(keyword, na=False) | \
           df['name'].str.upper().str.contains(keyword, na=False)
    results = df[mask].head(limit)

    return results.to_dict('records')


def fetch_stock_data(
    symbol: str,
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    adjust: str = "qfq"
) -> pd.DataFrame:
    """
    获取股票历史K线数据

    Args:
        symbol: 股票代码，如 "600519"
        period: 数据频率 - daily/weekly/monthly/1/5/15/30/60
        start_date: 开始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"
        adjust: 复权方式 - qfq(前复权)/hfq(后复权)/""(不复权)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    if start_date is None:
        start_date = "20200101"
    if end_date is None:
        end_date = pd.Timestamp.now().strftime("%Y%m%d")

    # 格式化日期为 YYYY-MM-DD
    start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # 频率映射
    freq_map = {
        "daily": "d", "weekly": "w", "monthly": "m",
        "5": "5", "15": "15", "30": "30", "60": "60",
    }
    bs_freq = freq_map.get(period, "d")

    # 复权映射
    adjust_map = {"qfq": "2", "hfq": "1", "": "3"}
    bs_adjust = adjust_map.get(adjust, "2")

    # 判断市场前缀
    if symbol.startswith(("sh", "sz")):
        bs_code = symbol
    elif symbol.startswith(("6", "9")):
        bs_code = f"sh.{symbol}"
    else:
        bs_code = f"sz.{symbol}"

    try:
        _bs_login()

        fields = "date,open,high,low,close,volume"
        rs = bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=start_fmt, end_date=end_fmt,
            frequency=bs_freq, adjustflag=bs_adjust
        )

        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        _bs_logout()

        if not data_list:
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)

        # 转换数据类型
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        # 去除无效行
        df = df.dropna(subset=['close'])
        df = df[df['close'] > 0]

        df = df.sort_values('date').reset_index(drop=True)
        return df

    except Exception as e:
        print(f"[baostock] 获取 {symbol} {period} 数据失败: {e}")
        try:
            _bs_logout()
        except:
            pass
        return pd.DataFrame()


def get_stock_name(symbol: str) -> str:
    """根据股票代码获取名称"""
    df = get_stock_list()
    if df.empty:
        return symbol
    match = df[df['code'] == symbol]
    if not match.empty:
        return match.iloc[0]['name']
    return symbol


if __name__ == "__main__":
    print("=== 测试股票搜索 ===")
    results = search_stocks("茅台")
    for r in results[:3]:
        print(f"  {r['code']} - {r['name']}")

    print("\n=== 测试数据获取 ===")
    df = fetch_stock_data("600519", period="daily", start_date="20250101")
    print(f"  获取到 {len(df)} 条记录")
    if not df.empty:
        print(df[['date', 'close']].tail(3))
