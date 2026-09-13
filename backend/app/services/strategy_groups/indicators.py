"""策略组回测用的轻量指标 —— 全部只用当前及更早数据，不含未来函数"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """平均真实波幅，Wilder 平滑"""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 6) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    avg_up = up.ewm(alpha=1 / n, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def kdj_k(df: pd.DataFrame, n: int = 9) -> pd.Series:
    low_n = df["low"].rolling(n, min_periods=n).min()
    high_n = df["high"].rolling(n, min_periods=n).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100).fillna(50.0)
    return rsv.ewm(alpha=1 / 3, adjust=False).mean()


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    return dif, dea


def exit_signal(df: pd.DataFrame, kind: str) -> pd.Series:
    """技术破位离场信号，信号日收盘判定，次日开盘执行"""
    close = df["close"]
    ma5 = ma(close, 5)
    ma10 = ma(close, 10)
    ma20 = ma(close, 20)
    ma60 = ma(close, 60)
    if kind == "trend":
        out = (close < ma20) | (close < ma60)
    elif kind == "pullback":
        out = (close < ma20) | (close < ma60)
    elif kind == "oversold":
        r = rsi(close, 6)
        k = kdj_k(df, 9)
        out = (r > 60) | (k > 60) | (close < ma5)
    elif kind == "momentum":
        out = (close < ma10) | (close < ma20)
    elif kind == "model":
        out = (close < ma20) | (close < ma60)
    else:
        out = pd.Series(False, index=df.index)
    return out.fillna(False).astype(bool)


def limit_pct(code: str) -> float:
    """按板块近似涨跌停幅度"""
    suffix = code.split(".")[-1]
    if suffix.startswith(("30", "68")):
        return 0.195
    return 0.095


def is_limit_up(open_price: float, prev_close: float, code: str) -> bool:
    if not prev_close or not open_price:
        return False
    return open_price / prev_close >= 1 + limit_pct(code)


def is_limit_down(open_price: float, prev_close: float, code: str) -> bool:
    if not prev_close or not open_price:
        return False
    return open_price / prev_close <= 1 - limit_pct(code)
