"""Gate 5 [E]: empat trigger yang boleh menghasilkan entry.

T1 Deviation + Reclaim (stop run / liquidity sweep)  - trigger utama
T2 Breakout -> Retest (flip level)
T3 Pullback Fibonacci 0.75 / 0.786
T4 Reclaim trendline / flip EMA

Semua logika ditulis untuk sisi LONG. Sisi SHORT = cermin: harga dinegasikan (flip), dijalankan
sebagai long, lalu hasilnya dinegasikan kembali. Dengan begitu long/short dijamin simetris.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .indicators import ema, last_atr, vol_ratio
from .levels import Level, confluence
from .structure import Impulse, pivots

ACTIVE = "ACTIVE"
PENDING_RETEST = "PENDING_RETEST"
PENDING_RECLAIM = "PENDING_RECLAIM"
PENDING_HOLD = "PENDING_HOLD"
MISSED = "MISSED"
FAILED = "FAILED"
PENDING_STATUSES = {PENDING_RETEST, PENDING_RECLAIM, PENDING_HOLD}


@dataclass
class Trigger:
    type: str
    direction: str  # long | short
    status: str
    entry: float
    stop: float
    level: float
    level_label: str = ""
    features: list[str] = field(default_factory=list)
    notes: str = ""
    atr: float = float("nan")  # ATR yang dipakai trigger ini (untuk klasifikasi/skor)
    tf: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "direction": self.direction,
            "status": self.status,
            "entry": round(self.entry, 8),
            "stop": round(self.stop, 8),
            "level": round(self.level, 8),
            "level_label": self.level_label,
            "features": self.features,
            "notes": self.notes,
            "tf": self.tf,
        }


# --------------------------------------------------------------- mirror
def flip(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["open"] = -df["open"]
    d["close"] = -df["close"]
    d["high"] = -df["low"]
    d["low"] = -df["high"]
    return d


def _unflip(tr: Trigger | None) -> Trigger | None:
    if tr is None:
        return None
    return replace(tr, direction="short", entry=-tr.entry, stop=-tr.stop, level=-tr.level)


def flip_impulse(imp: Impulse) -> Impulse:
    return Impulse(
        "up" if imp.direction == "down" else "down",
        -imp.start,
        -imp.end,
        imp.end_idx,
        imp.intact,
        {r: -p for r, p in imp.fibs.items()},
    )


def classify(price: float, entry: float, stop: float, atr: float, cfg) -> str:
    """Status relatif terhadap harga sekarang (sisi long). Jangan mengejar harga [E]."""
    t = cfg.triggers
    if price <= stop:
        return FAILED
    if price <= entry + t.retest_tol_atr * atr:
        return ACTIVE
    if price - entry <= t.chase_limit_atr * atr:
        return PENDING_RETEST
    return MISSED


def _wick_ratio_lower(row) -> float:
    rng = float(row["high"] - row["low"])
    if rng <= 0:
        return 0.0
    return float(min(row["open"], row["close"]) - row["low"]) / rng


# ------------------------------------------------------------------- T1
def _t1_long(df: pd.DataFrame, L: float, atr: float, cfg) -> Trigger | None:
    c = cfg.triggers.t1
    n = int(c.lookback_bars)
    if len(df) < n + 25:
        return None
    w = df.iloc[-n:].reset_index(drop=True)
    vr = vol_ratio(df).iloc[-n:].reset_index(drop=True)
    sweep_min = c.sweep_min_atr * atr
    max_rec = int(c.max_reclaim_bars)

    state: str | None = None
    episodes: list[dict] = []
    off = len(df) - n
    for i in range(len(w)):
        low, close = float(w.at[i, "low"]), float(w.at[i, "close"])
        prev_close = float(df["close"].iloc[off + i - 1])
        # sapuan hanya sah bila harga datang dari ATAS level (level berfungsi sebagai support)
        if state in (None, "reclaimed") and low < L - sweep_min and prev_close > L:
            episodes.append({"s": i, "r": None, "ext": low, "failed": False})
            state = "active"
        elif state == "active":
            episodes[-1]["ext"] = min(episodes[-1]["ext"], low)
        if state == "active":
            ep = episodes[-1]
            if close > L and (i - ep["s"]) <= max_rec:
                ep["r"] = i
                state = "reclaimed"
            elif (i - ep["s"]) > max_rec:  # reclaim terlambat = bukan stop run cepat
                ep["failed"] = True
                state = None
        elif state == "reclaimed":
            if close < L:
                episodes[-1]["failed"] = True
                state = None
    if not episodes:
        return None

    ep = episodes[-1]
    price = float(w["close"].iloc[-1])
    stop = ep["ext"] - c.stop_buffer_atr * atr
    entry = L
    end_i = ep["r"] if ep["r"] is not None else len(w) - 1
    feats: list[str] = []
    if float(vr.iloc[ep["s"] : end_i + 1].max()) >= c.volume_mult:
        feats.append("volume_spike")
    if any(_wick_ratio_lower(w.iloc[j]) >= c.wick_ratio for j in range(ep["s"], end_i + 1)):
        feats.append("wick_rejection")
    if sum(1 for e in episodes if e["r"] is not None) >= 2:
        feats.append("double_deviation")
    ph, pl = pivots(df.iloc[-60:].reset_index(drop=True), 2)
    if sum(1 for _, p in pl if abs(p - L) <= c.three_tap_tol_atr * atr) >= 3:
        feats.append("three_tap")

    base = dict(type="T1", direction="long", entry=entry, stop=stop, level=L, features=feats, atr=atr)
    if ep["failed"] or state is None:
        return Trigger(status=FAILED, notes="deviasi gagal reclaim", **base)
    if state == "active":
        return Trigger(status=PENDING_RECLAIM, notes="sapuan terjadi, menunggu close kembali di atas level", **base)
    if c.require_quality_feature and not feats:
        return Trigger(status=FAILED, notes="sapuan lemah (tanpa volume/wick/double/three-tap)", **base)
    st = classify(price, entry, stop, atr, cfg)
    note = {
        ACTIVE: "sapuan + reclaim, harga di zona retest",
        PENDING_RETEST: "sapuan + reclaim; pasang limit di level retest",
        MISSED: "sudah lari jauh dari level, jangan dikejar",
        FAILED: "harga kembali menembus stop",
    }[st]
    return Trigger(status=st, notes=note, **base)


def t1(df15: pd.DataFrame, L: float, direction: str, cfg) -> Trigger | None:
    atr = last_atr(df15)
    if not np.isfinite(atr):
        return None
    if direction == "long":
        tr = _t1_long(df15, L, atr, cfg)
    else:
        tr = _unflip(_t1_long(flip(df15), -L, atr, cfg))
    if tr is not None:
        tr.tf = cfg.triggers.tf_trigger
    return tr


# ------------------------------------------------------------------- T2
def _t2_long(df: pd.DataFrame, L: float, atr: float, cfg) -> Trigger | None:
    c = cfg.triggers.t2
    n = int(c.lookback_bars)
    if len(df) < n + 25:
        return None
    w = df.iloc[-n:].reset_index(drop=True)
    vr = vol_ratio(df).iloc[-n:].reset_index(drop=True)
    eps = c.eps_atr * atr
    b = None
    for i in range(1, len(w)):
        if w.at[i, "close"] > L + eps and w.at[i - 1, "close"] <= L + eps:
            b = i
    if b is None:
        return None
    price = float(w["close"].iloc[-1])
    low_b = float(w.at[b, "low"])
    stop = min(L, low_b) - c.stop_buffer_atr * atr
    base = dict(type="T2", direction="long", entry=L, stop=stop, level=L, atr=atr)
    since = w.iloc[b:]
    if (since["close"] <= L).any():
        return Trigger(status=FAILED, features=["failed_breakout"], notes="breakout palsu: close kembali ke dalam", **base)
    feats: list[str] = []
    if float(vr.iloc[b : b + 2].max()) >= c.volume_mult:
        feats.append("volume_spike")
    elif c.require_volume:
        return Trigger(status=FAILED, features=[], notes="breakout tanpa volume", **base)
    if len(since) < int(c.hold_bars):
        return Trigger(status=PENDING_HOLD, features=feats, notes="menunggu konsolidasi di atas level", **base)
    st = classify(price, L, stop, atr, cfg)
    note = {
        ACTIVE: "breakout bervolume + hold, harga di retest",
        PENDING_RETEST: "breakout bervolume + hold; pasang limit di retest",
        MISSED: "breakout sudah lari jauh, jangan dikejar",
        FAILED: "harga kembali menembus stop",
    }[st]
    return Trigger(status=st, features=feats, notes=note, **base)


def t2(df1h: pd.DataFrame, L: float, direction: str, cfg) -> Trigger | None:
    atr = last_atr(df1h)
    if not np.isfinite(atr):
        return None
    if direction == "long":
        tr = _t2_long(df1h, L, atr, cfg)
    else:
        tr = _unflip(_t2_long(flip(df1h), -L, atr, cfg))
    if tr is not None:
        tr.tf = "1h"
    return tr


# ------------------------------------------------------------------- T3
def _t3_long(df15: pd.DataFrame, imp: Impulse, atr15: float, atr1h: float, cfg) -> Trigger | None:
    c = cfg.triggers.t3
    if imp.direction != "up" or not imp.intact:
        return None
    zone_hi, zone_lo = imp.fibs[0.75], imp.fibs[0.786]
    buf = c.stop_buffer_atr * atr1h
    n = int(c.reaction_lookback_bars)
    w = df15.iloc[-n:].reset_index(drop=True)
    price = float(w["close"].iloc[-1])
    tol = 0.2 * atr15
    touched = [i for i in range(len(w)) if w.at[i, "low"] <= zone_hi + tol]
    base = dict(type="T3", direction="long", entry=zone_hi, level=zone_hi, atr=atr1h)
    if not touched:
        if price > zone_hi and (price - zone_hi) <= 2.0 * atr1h:
            return Trigger(status=PENDING_RETEST, stop=zone_lo - buf, features=[], notes="harga mendekati zona fib 0.75-0.786", **base)
        return None
    t0 = touched[0]
    low_since = float(w["low"].iloc[t0:].min())
    if low_since < imp.start:
        return None
    if low_since < zone_lo - 0.5 * atr1h:
        return Trigger(status=FAILED, stop=zone_lo - buf, features=[], notes="menembus dalam melewati 0.786", **base)
    stop = min(low_since, zone_lo) - buf
    feats: list[str] = []
    vr = vol_ratio(df15).iloc[-n:].reset_index(drop=True)
    if float(vr.iloc[t0:].max()) >= cfg.confirmations.volume_spike_mult:
        feats.append("volume_spike")
    if any(_wick_ratio_lower(w.iloc[j]) >= cfg.confirmations.wick_ratio for j in range(t0, len(w))):
        feats.append("wick_rejection")
    if price > zone_hi:
        st = classify(price, zone_hi, stop, atr1h, cfg)
        return Trigger(status=st, stop=stop, features=feats, notes="zona fib tersentuh lalu direclaim", **base)
    return Trigger(status=PENDING_RECLAIM, stop=stop, features=feats, notes="harga di zona fib, menunggu reclaim 0.75", **base)


def t3(df15: pd.DataFrame, imp: Impulse | None, direction: str, levels: list[Level], atr1h: float, cfg) -> Trigger | None:
    if imp is None or not imp.intact:
        return None
    atr15 = last_atr(df15)
    if not (np.isfinite(atr15) and np.isfinite(atr1h)):
        return None
    want = "up" if direction == "long" else "down"
    if imp.direction != want:
        return None
    use = imp if direction == "long" else flip_impulse(imp)
    tr = _t3_long(flip(df15) if direction == "short" else df15, use, atr15, atr1h, cfg)
    if direction == "short":
        tr = _unflip(tr)
    if tr is None:
        return None
    if cfg.triggers.t3.require_confluence:
        others = [x for x in levels if not x.kind.startswith("fib_")]
        tol = cfg.levels.confluence_tol_atr * atr1h
        score, used = confluence(tr.entry, others, tol, exclude_self=False)
        if score < 0.5:
            return None
        tr.features = tr.features + ["confluence:" + "+".join(sorted({u.kind for u in used}))]
    tr.tf = cfg.triggers.tf_trigger
    return tr


# ------------------------------------------------------------------- T4
def _t4_ema_long(df: pd.DataFrame, atr: float, cfg) -> Trigger | None:
    c = cfg.triggers.t4
    e = ema(df["close"], int(c.ema_len))
    lb = int(c.lookback_bars)
    w = df.iloc[-(lb + 1) :].reset_index(drop=True)
    ew = e.iloc[-(lb + 1) :].reset_index(drop=True)
    below = any(w.at[i, "close"] < ew.at[i] for i in range(len(w) - 2))
    if not below:
        return None
    if not (w.at[len(w) - 1, "close"] > ew.iloc[-1] and w.at[len(w) - 2, "close"] > ew.iloc[-2]):
        return None
    entry = float(ew.iloc[-1])
    stop = min(float(w["low"].iloc[-4:].min()), entry) - c.stop_buffer_atr * atr
    price = float(w["close"].iloc[-1])
    st = classify(price, entry, stop, atr, cfg)
    feats = ["ema_flip"]
    e50 = ema(df["close"], 50).iloc[-1]
    if ew.iloc[-1] > e50:
        feats.append("ema20>ema50")
    return Trigger(type="T4", direction="long", status=st, entry=entry, stop=stop, level=entry, level_label="EMA20 1H",
                   features=feats, notes="harga flip EMA20 dan menahan", atr=atr)


def _t4_trendline_long(df: pd.DataFrame, atr: float, cfg) -> Trigger | None:
    c = cfg.triggers.t4
    d = df.iloc[-120:].reset_index(drop=True)
    ph, _ = pivots(d, 3)
    if len(ph) < 2:
        return None
    (i1, p1), (i2, p2) = ph[-2], ph[-1]
    if p2 >= p1 or i2 == i1:
        return None  # butuh resistance menurun
    slope = (p2 - p1) / (i2 - i1)

    def line(i: int) -> float:
        return p2 + slope * (i - i2)

    n = len(d)
    last = n - 1
    if d.at[last, "close"] <= line(last):
        return None
    was_below = any(d.at[i, "close"] < line(i) for i in range(max(i2 + 1, n - 7), last))
    if not was_below:
        return None
    entry = float(line(last))
    stop = min(float(d["low"].iloc[-4:].min()), entry) - c.stop_buffer_atr * atr
    price = float(d.at[last, "close"])
    st = classify(price, entry, stop, atr, cfg)
    return Trigger(type="T4", direction="long", status=st, entry=entry, stop=stop, level=entry, level_label="Trendline turun",
                   features=["trendline_reclaim"], notes="trendline direclaim", atr=atr)


def t4(df1h: pd.DataFrame, direction: str, cfg) -> list[Trigger]:
    atr = last_atr(df1h)
    if not np.isfinite(atr) or len(df1h) < 130:
        return []
    src = df1h if direction == "long" else flip(df1h)
    out: list[Trigger] = []
    for fn in (_t4_ema_long, _t4_trendline_long):
        tr = fn(src, atr, cfg)
        if tr is not None:
            tr = tr if direction == "long" else _unflip(tr)
            tr.tf = "1h"
            out.append(tr)
    return out


# ---------------------------------------------------------------- scanner
def _dedupe_levels(levels: list[Level], tol: float) -> list[Level]:
    out: list[Level] = []
    for lv in sorted(levels, key=lambda x: -x.weight):
        if all(abs(lv.price - o.price) > tol for o in out):
            out.append(lv)
    return out


def scan_triggers(data: dict, levels: list[Level], impulse: Impulse | None, cfg) -> list[Trigger]:
    """Cari semua trigger (kedua arah). Filter musim/rezim dilakukan di engine."""
    df15, df1h = data["15m"], data["1h"]
    price = float(df15["close"].iloc[-1])
    atr1h = last_atr(df1h)
    if not np.isfinite(atr1h):
        return []
    near = [x for x in levels if abs(x.price - price) <= 3.0 * atr1h and x.weight >= cfg.triggers.min_level_weight]
    cands = _dedupe_levels(near, 0.15 * atr1h)[:14]
    found: list[Trigger] = []
    for lv in cands:
        for d in ("long", "short"):
            for fn, df in ((t1, df15), (t2, df1h)):
                tr = fn(df, lv.price, d, cfg)
                if tr is not None:
                    tr.level_label = lv.label
                    found.append(tr)
    for d in ("long", "short"):
        tr3 = t3(df15, impulse, d, levels, atr1h, cfg)
        if tr3 is not None:
            tr3.level_label = "Fib 0.75-0.786"
            found.append(tr3)
        found.extend(t4(df1h, d, cfg))
    return found
