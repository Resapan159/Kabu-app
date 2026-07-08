"""テクニカル指標の計算。すべて pandas.Series / DataFrame ベース。

入力の OHLCV DataFrame は次の列を想定: Open, High, Low, Close, Volume（時系列昇順）。
外部ライブラリ(ta-lib等)に依存せず、pandas/numpy のみで実装している。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder平滑化 = alpha 1/period の EMA
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # avg_loss=0（連続上昇）のときは100
    out = out.where(avg_loss != 0, 100.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD線・シグナル線・ヒストグラムを返す。"""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    """ボリンジャーバンドの上限・中心・下限・バンド幅(%)を返す。"""
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width_pct = (upper - lower) / mid * 100
    return upper, mid, lower, width_pct


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range（Wilder平滑化）。"""
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def cross_up(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """fast が slow を下から上に抜けた点を True にする Bool Series。"""
    prev = fast.shift(1) <= slow.shift(1)
    now = fast > slow
    return prev & now


def recent_true(mask: pd.Series, within: int) -> bool:
    """直近 within 本の中に True があるか。"""
    if len(mask) == 0:
        return False
    return bool(mask.tail(within).any())
