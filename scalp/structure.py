"""Struktur pasar: pivot, "musim" tren (Gate 2), range (Gate 3), FVG, impuls Fibonacci."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import ema, last_atr


# ----------------------------------------------------------------- pivots
def pivots(df: pd.DataFrame, k: int = 3) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Pivot high/low yang sudah terkonfirmasi (k candle di kiri dan kanan)."""
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    n = len(df)
    ph: list[tuple[int, float]] = []
    pl: list[tuple[int, float]] = []
    for i in range(k, n - k):
        wh = hi[i - k : i + k + 1]
        wl = lo[i - k : i + k + 1]
        if hi[i] >= wh.max() and hi[i] > hi[i - 1]:
            ph.append((i, float(hi[i])))
        if lo[i] <= wl.min() and lo[i] < lo[i - 1]:
            pl.append((i, float(lo[i])))
    return ph, pl


def _tf_structure_score(df: pd.DataFrame, k: int) -> tuple[float, dict]:
    ph, pl = pivots(df, k)
    s = 0.0
    detail: dict = {}
    if len(ph) >= 2 and len(pl) >= 2:
        hh = ph[-1][1] > ph[-2][1]
        hl = pl[-1][1] > pl[-2][1]
        if hh and hl:
            s += 2
            detail["structure"] = "HH/HL"
        elif (not hh) and (not hl):
            s -= 2
            detail["structure"] = "LH/LL"
        else:
            detail["structure"] = "campuran"
    e20, e50 = ema(df["close"], 20), ema(df["close"], 50)
    s += 1 if e20.iloc[-1] > e50.iloc[-1] else -1
    s += 1 if df["close"].iloc[-1] > e50.iloc[-1] else -1
    detail["ema20_gt_ema50"] = bool(e20.iloc[-1] > e50.iloc[-1])
    detail["close_gt_ema50"] = bool(df["close"].iloc[-1] > e50.iloc[-1])
    return s, detail


def season(df1d: pd.DataFrame, df4h: pd.DataFrame, cfg) -> dict:
    """Gate 2 [E]: LONG_SEASON / SHORT_SEASON / NEUTRAL_RANGE."""
    s1, d1 = _tf_structure_score(df1d, 3)
    s4, d4 = _tf_structure_score(df4h, 3)
    total = s1 + s4
    if total >= cfg.gate2_season.long_threshold:
        name = "LONG_SEASON"
    elif total <= cfg.gate2_season.short_threshold:
        name = "SHORT_SEASON"
    else:
        name = "NEUTRAL_RANGE"
    return {"season": name, "score": float(total), "1d": d1, "4h": d4}


# ------------------------------------------------------------------ range
@dataclass
class Range:
    valid: bool
    high: float = float("nan")
    low: float = float("nan")
    touches_high: int = 0
    touches_low: int = 0
    exclude_recent: int = 0
    reason: str = ""

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def height(self) -> float:
        return self.high - self.low

    def pct(self, price: float) -> float:
        """Posisi harga dalam range: 0 = RL, 1 = RH (bisa <0 atau >1)."""
        if not self.valid or self.height <= 0:
            return float("nan")
        return (price - self.low) / self.height

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "high": None if not self.valid else round(self.high, 8),
            "low": None if not self.valid else round(self.low, 8),
            "mid": None if not self.valid else round(self.mid, 8),
            "touches_high": self.touches_high,
            "touches_low": self.touches_low,
            "reason": self.reason,
        }


def _range_for(df1h: pd.DataFrame, atr1h: float, cfg, excl: int) -> Range:
    c = cfg.gate3_range
    lb = int(c.lookback_bars)
    if len(df1h) < lb + excl + 5:
        return Range(False, reason="data 1H kurang")
    w = df1h.iloc[-(lb + excl) : len(df1h) - excl].reset_index(drop=True)
    rh, rl = float(w["high"].max()), float(w["low"].min())
    height = rh - rl
    if height <= 0 or not np.isfinite(atr1h):
        return Range(False, reason="range nol")
    tol = c.touch_tol_atr * atr1h
    ph, pl = pivots(w, int(c.pivot_k))
    th = sum(1 for _, p in ph if p >= rh - tol)
    tl = sum(1 for _, p in pl if p <= rl + tol)
    h_atr = height / atr1h
    drift = abs(float(w["close"].iloc[-1] - w["close"].iloc[0])) / height
    reasons = []
    if th < c.min_touches or tl < c.min_touches:
        reasons.append(f"sentuhan kurang (atas {th}, bawah {tl})")
    if h_atr < c.min_height_atr:
        reasons.append("range terlalu sempit")
    if h_atr > c.max_height_atr:
        reasons.append("range terlalu lebar")
    if drift > c.max_drift:
        reasons.append("harga trending, bukan range")
    return Range(not reasons, rh, rl, th, tl, excl, "; ".join(reasons))


def detect_range(df1h: pd.DataFrame, cfg) -> Range:
    """Gate 3 [E]: cari box H1; coba beberapa offset agar breakout lama tidak merusak batas."""
    atr1h = last_atr(df1h)
    last: Range | None = None
    for excl in cfg.gate3_range.exclude_recent_options:
        r = _range_for(df1h, atr1h, cfg, int(excl))
        last = last or r
        if r.valid:
            return r
    return last or Range(False, reason="tidak ada data")


def location(rng: Range, price: float, cfg) -> dict:
    """Klasifikasi lokasi harga terhadap range."""
    if not rng.valid:
        return {"zone": "NO_RANGE", "pct_of_range": None}
    p = rng.pct(price)
    lo_mid, hi_mid = cfg.gate3_range.mid_zone
    edge = cfg.gate3_range.edge_zone
    if p <= edge:
        z = "RL"
    elif p >= 1 - edge:
        z = "RH"
    elif lo_mid <= p <= hi_mid:
        z = "MID"
    else:
        z = "OTHER"
    return {"zone": z, "pct_of_range": round(float(p), 4)}


# -------------------------------------------------------------------- FVG
def find_fvgs(df: pd.DataFrame, atr_val: float, min_gap_atr: float, lookback: int = 80) -> list[dict]:
    """Fair Value Gap yang belum terisi penuh. dir: 'bull' (support) atau 'bear' (resistance)."""
    n = len(df)
    start = max(2, n - lookback)
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    out: list[dict] = []
    for i in range(start, n):
        if lo[i] > hi[i - 2] and (lo[i] - hi[i - 2]) >= min_gap_atr * atr_val:
            zl, zh = float(hi[i - 2]), float(lo[i])
            later = lo[i + 1 :]
            if later.size == 0 or later.min() > zl:
                out.append({"dir": "bull", "low": zl, "high": zh, "i": i})
        if hi[i] < lo[i - 2] and (lo[i - 2] - hi[i]) >= min_gap_atr * atr_val:
            zl, zh = float(hi[i]), float(lo[i - 2])
            later = hi[i + 1 :]
            if later.size == 0 or later.max() < zh:
                out.append({"dir": "bear", "low": zl, "high": zh, "i": i})
    return out


# ---------------------------------------------------------------- impulse
@dataclass
class Impulse:
    direction: str  # 'up' atau 'down'
    start: float  # asal impuls (low utk up, high utk down)
    end: float  # ujung impuls (high utk up, low utk down)
    end_idx: int
    intact: bool = True
    fibs: dict = field(default_factory=dict)

    @property
    def size(self) -> float:
        return abs(self.end - self.start)


def last_impulse(df: pd.DataFrame, atr_val: float, cfg, k: int = 4, window: int = 240) -> Impulse | None:
    """Impuls terakhir yang selesai (swing low->high atau high->low) dengan ukuran >= min_impulse_atr."""
    d = df.iloc[-window:].reset_index(drop=True)
    ph, pl = pivots(d, k)
    pts = sorted([(i, p, "H") for i, p in ph] + [(i, p, "L") for i, p in pl])
    alt: list[tuple[int, float, str]] = []
    for pt in pts:  # paksa bergantian, simpan yang paling ekstrem
        if alt and alt[-1][2] == pt[2]:
            if (pt[2] == "H" and pt[1] > alt[-1][1]) or (pt[2] == "L" and pt[1] < alt[-1][1]):
                alt[-1] = pt
        else:
            alt.append(pt)
    min_size = cfg.levels.min_impulse_atr * atr_val
    for j in range(len(alt) - 1, 0, -1):
        a, b = alt[j - 1], alt[j]
        if abs(b[1] - a[1]) < min_size:
            continue
        direction = "up" if (a[2] == "L" and b[2] == "H") else "down"
        imp = Impulse(direction, a[1], b[1], len(df) - len(d) + b[0])
        after = d.iloc[b[0] + 1 :]
        if direction == "up":
            imp.intact = bool(after.empty or after["low"].min() > a[1])
            imp.fibs = {r: b[1] - r * (b[1] - a[1]) for r in cfg.levels.fib_ratios}
        else:
            imp.intact = bool(after.empty or after["high"].max() < a[1])
            imp.fibs = {r: b[1] + r * (a[1] - b[1]) for r in cfg.levels.fib_ratios}
        return imp
    return None
