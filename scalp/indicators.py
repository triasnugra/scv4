"""Indikator dasar. Semua berbasis candle tertutup."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def last_atr(df: pd.DataFrame, n: int = 14) -> float:
    v = float(atr(df, n).iloc[-1])
    return v if np.isfinite(v) and v > 0 else float("nan")


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def vol_ratio(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Volume dibanding rata-rata n candle sebelumnya (tanpa candle itu sendiri)."""
    base = df["volume"].shift(1).rolling(n, min_periods=max(5, n // 2)).mean()
    return (df["volume"] / base.replace(0, np.nan)).fillna(1.0)
