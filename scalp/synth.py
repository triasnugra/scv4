"""Data sintetis untuk tes unit dan demo offline (BUKAN data pasar)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import TF_SECONDS, drop_unclosed


def make_5m(close: np.ndarray, end: pd.Timestamp, seed: int = 7, vol_mean: float = 2000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(close)
    times = pd.date_range(end=end - pd.Timedelta(minutes=5), periods=n, freq="5min", tz="UTC")
    open_ = np.concatenate([[close[0]], close[:-1]])
    wick_hi = np.abs(rng.normal(0, 0.0007, n)) * close
    wick_lo = np.abs(rng.normal(0, 0.0007, n)) * close
    high = np.maximum(open_, close) + wick_hi
    low = np.minimum(open_, close) - wick_lo
    vol = rng.lognormal(mean=np.log(vol_mean), sigma=0.35, size=n)
    return pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close, "volume": vol})


def resample(df5: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "5m":
        return df5.copy()
    sec = TF_SECONDS[tf]
    per = sec // 300
    key = df5["time"].dt.floor(f"{sec}s")
    g = df5.groupby(key)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                volume=("volume", "sum"), n=("close", "size")).reset_index().rename(columns={"time": "time"})
    out = out[out["n"] == per].drop(columns="n").reset_index(drop=True)
    return out


def all_tfs(df5: pd.DataFrame, now: pd.Timestamp) -> dict:
    return {tf: drop_unclosed(resample(df5, tf), tf, now) for tf in ("5m", "15m", "1h", "4h", "1d")}


def ranging_close(n: int, base: float = 100.0, amp: float = 0.015, period: int = 288, noise: float = 0.0006,
                  seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    c = base * (1 + amp * np.sin(2 * np.pi * t / period))
    return c * (1 + rng.normal(0, noise, n))


def sweep_reclaim_scenario(direction: str = "long", days: int = 120, now: str = "2026-11-11 12:00", seed: int = 3):
    """Range berosilasi, lalu sapuan di tepi range dan reclaim + retest di akhir."""
    now_ts = pd.Timestamp(now, tz="UTC")
    n = days * 288
    close = ranging_close(n, seed=seed)
    # tepi range (perkiraan dari sinusoid)
    rl, rh = 100 * (1 - 0.015), 100 * (1 + 0.015)
    tail = 60
    start = close[n - tail - 1]
    seg = np.empty(tail)
    if direction == "long":
        edge = rl
        seg[:30] = np.linspace(start, edge * 1.004, 30)
        seg[30:34] = [edge * 0.998, edge * 0.994, edge * 0.992, edge * 0.996]
        seg[34:38] = [edge * 1.002, edge * 1.005, edge * 1.007, edge * 1.006]
        seg[38:] = np.linspace(edge * 1.006, edge * 1.0025, tail - 38)
    else:
        edge = rh
        seg[:30] = np.linspace(start, edge * 0.996, 30)
        seg[30:34] = [edge * 1.002, edge * 1.006, edge * 1.008, edge * 1.004]
        seg[34:38] = [edge * 0.998, edge * 0.995, edge * 0.993, edge * 0.994]
        seg[38:] = np.linspace(edge * 0.994, edge * 0.9975, tail - 38)
    close[n - tail :] = seg
    df5 = make_5m(close, now_ts, seed=seed + 11)
    # lonjakan volume saat sapuan
    df5.loc[df5.index[n - tail + 30 : n - tail + 38], "volume"] *= 4.0
    return all_tfs(df5, now_ts), now_ts, edge


def mid_range_scenario(days: int = 120, now: str = "2026-11-11 12:00", seed: int = 5):
    """Harga tepat di tengah range (fase sinus = 0 di candle terakhir)."""
    now_ts = pd.Timestamp(now, tz="UTC")
    n = days * 288 + 1
    close = ranging_close(n, seed=seed)
    df5 = make_5m(close, now_ts, seed=seed + 11)
    return all_tfs(df5, now_ts), now_ts


def demo_data(symbols: list[str], now: pd.Timestamp | None = None) -> dict:
    """Data demo untuk satu set simbol (offline)."""
    now = now or pd.Timestamp("2026-11-11 12:00", tz="UTC")
    out = {}
    for i, s in enumerate(symbols):
        d, _, _ = sweep_reclaim_scenario("long" if i % 2 == 0 else "short", seed=3 + i, now=str(now.tz_convert(None)))
        out[s] = d
    return out, now
