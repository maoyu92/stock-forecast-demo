"""多因子数据获取模块 - 以中国太保为例"""
import pandas as pd
from typing import Optional, Dict, List
from .stock_fetcher import fetch_stock_data, get_stock_name, search_stocks

PRESET_MULTI_FACTOR = {
    '中国太保': {
        'target': '601318',
        'factors': [
            {'label': '中国太保', 'code': '601318', 'type': 'target'},
            {'label': '保险ETF', 'code': '512800', 'type': 'industry_etf'},
            {'label': '沪深300ETF', 'code': '510300', 'type': 'market_etf'},
            {'label': '纳斯达克ETF', 'code': '513300', 'type': 'us_etf'},
        ]
    }
}


def resolve_preset(name: str) -> Optional[Dict]:
    name = name.strip()
    if name in PRESET_MULTI_FACTOR:
        return PRESET_MULTI_FACTOR[name]
    results = search_stocks(name, limit=5)
    if not results:
        return None
    best = results[0]
    code = best['code']
    label = best['name']
    return {
        'target': code,
        'factors': [
            {'label': label, 'code': code, 'type': 'target'},
            {'label': '保险ETF', 'code': '512800', 'type': 'industry_etf'},
            {'label': '沪深300ETF', 'code': '510300', 'type': 'market_etf'},
            {'label': '纳斯达克ETF', 'code': '513300', 'type': 'us_etf'},
        ]
    }


def fetch_multi_factors(
    symbol: str,
    period: str = 'daily',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    factors: Optional[List[Dict]] = None,
) -> pd.DataFrame:
    if factors is None:
        preset = resolve_preset(symbol)
        if preset is None:
            return pd.DataFrame()
        factors = preset['factors']
        symbol = preset['target']

    frames: Dict[str, pd.Series] = {}
    for f in factors:
        df = fetch_stock_data(f['code'], period=period, start_date=start_date, end_date=end_date)
        if df.empty:
            continue
        s = df.set_index('date')['close'].sort_index()
        s.name = f['label']
        frames[f['label']] = s

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames.values(), axis=1).sort_index()
    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors='coerce')
    out = out.dropna(how='all')
    out = out.ffill().bfill()
    return out


def get_factor_meta(symbol: str) -> Optional[Dict]:
    return resolve_preset(symbol)


if __name__ == '__main__':
    import datetime
    end = datetime.datetime.now().strftime('%Y%m%d')
    start = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y%m%d')
    df = fetch_multi_factors('中国太保', period='daily', start_date=start, end_date=end)
    print(df.tail())
    print('shape', df.shape)
