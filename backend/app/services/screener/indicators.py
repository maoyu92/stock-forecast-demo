"""技术指标计算 —— pandas 手写实现（不引入 talib）

全部基于日 K DataFrame（列: date, open, high, low, close, volume），
与通达信口径保持一致：MACD 柱 = 2×(DIF−DEA)。
"""
import pandas as pd


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
         ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (DIF, DEA, MACD柱)，柱 = 2×(DIF−DEA)，红柱为正"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return dif, dea, (dif - dea) * 2


def has_recent_golden_cross(dif: pd.Series, dea: pd.Series, within: int = 3) -> bool:
    """最近 within 根K线内 DIF 是否上穿 DEA（金叉）"""
    d = dif.tail(within + 1).reset_index(drop=True)
    e = dea.tail(within + 1).reset_index(drop=True)
    for i in range(1, len(d)):
        if d.iloc[i - 1] <= e.iloc[i - 1] and d.iloc[i] > e.iloc[i]:
            return True
    return False


def is_limit_up(df: pd.DataFrame, i: int, threshold: float = 9.8) -> bool:
    """第 i 行是否涨停封板：涨幅 ≥ threshold% 且收盘价=最高价（封住）。

    主板 10% 涨停因四舍五入实际落在 9.8%~10.1%，用 9.8% 做下限近似。
    """
    if i < 1:
        return False
    prev_close = float(df["close"].iloc[i - 1])
    close = float(df["close"].iloc[i])
    high = float(df["high"].iloc[i])
    if prev_close <= 0:
        return False
    pct = (close / prev_close - 1) * 100
    return pct >= threshold and close >= high - 1e-9


def resistance_space(df: pd.DataFrame, window: int = 60) -> float:
    """压力位空间 (%) = (近 window 日最高价 − 现价) / 现价 × 100"""
    resist = float(df["high"].tail(window).max())
    close = float(df["close"].iloc[-1])
    if close <= 0:
        return 0.0
    return (resist - close) / close * 100


def has_unfilled_gap_up(df: pd.DataFrame, lookback: int = 5) -> bool:
    """近 lookback 日是否存在未回补的向上跳空缺口（当日最低 > 昨日最高，且现价仍在缺口上沿之上）"""
    n = len(df)
    close_now = float(df["close"].iloc[-1])
    for i in range(max(1, n - lookback), n):
        prev_high = float(df["high"].iloc[i - 1])
        low = float(df["low"].iloc[i])
        if prev_high > 0 and low > prev_high and close_now >= prev_high:
            return True
    return False


def daily_volatility_pct(df: pd.DataFrame, window: int = 20) -> float:
    """近 window 日收盘价日收益率标准差 (%)——风险度量"""
    ret = df["close"].pct_change().tail(window + 1).dropna()
    if len(ret) < 5:
        return float("nan")
    return float(ret.std() * 100)


def eval_prev_limit_up(df: pd.DataFrame, snapshot_pct: float,
                       tolerance: float = 0.35) -> tuple[bool, str]:
    """评估"前一交易日涨停封板"。

    快照代表的"当前会话"可能与 K 线最后一行是同一天（收盘后/非交易时段，baostock 已更新），
    也可能滞后一天（盘中运行 / EOD 未更新）。用涨跌幅数值比对判断：
    快照涨跌幅 ≈ K线最后一行涨跌幅 → 会话即最后一行，前一交易日取倒数第二行；否则取最后一行。
    返回 (是否涨停封板, 评估日文本)。
    """
    close = df["close"]
    if len(close) < 2:
        return False, ""
    last_pct = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
    same_session = abs(last_pct - float(snapshot_pct)) < tolerance
    idx = -2 if same_session else -1
    return is_limit_up(df, len(df) + idx), str(df["date"].iloc[idx].date())


def slope_up(s: pd.Series, compare_bars: int = 10) -> bool:
    """均线是否向上：当前值 > compare_bars 根之前（去 NaN 后比较）"""
    s = s.dropna()
    if len(s) <= compare_bars:
        return False
    return bool(s.iloc[-1] > s.iloc[-1 - compare_bars])
