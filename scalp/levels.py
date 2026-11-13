"""Gate 4 [E]: peta level + confluence (range edge, Monday range, prev day/week, FVG, fib, EMA, pivot HTF)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import ema, last_atr
from .structure import Impulse, Range, find_fvgs, last_impulse, pivots


@dataclass
class Level:
    price: float
    kind: str  # kunci bobot di config.levels.weights
    label: str
    tf: str
    weight: float

    def to_dict(self) -> dict:
        return {"price": round(self.price, 8), "kind": self.kind, "label": self.label, "tf": self.tf, "weight": self.weight}


def _w(cfg, kind: str) -> float:
    return float(cfg.levels.weights.get(kind, 0.3))


def monday_range(df1h: pd.DataFrame, now: pd.Timestamp) -> tuple[float, float, bool] | None:
    """High/low hari Senin (UTC) pada pekan berjalan. Return (hi, lo, complete)."""
    today = now.normalize()
    monday = today - pd.Timedelta(days=int(today.weekday()))
    sel = df1h[(df1h["time"] >= monday) & (df1h["time"] < monday + pd.Timedelta(days=1))]
    if len(sel) < 6:
        return None
    complete = now >= monday + pd.Timedelta(days=1)
    return float(sel["high"].max()), float(sel["low"].min()), bool(complete)


def prev_day(df1d: pd.DataFrame) -> tuple[float, float] | None:
    if len(df1d) < 2:
        return None
    r = df1d.iloc[-1]
    return float(r["high"]), float(r["low"])


def prev_week(df1d: pd.DataFrame, now: pd.Timestamp) -> tuple[float, float] | None:
    iso = df1d["time"].dt.isocalendar()
    cur = now.isocalendar()
    cur_key = int(cur[0]) * 100 + int(cur[1])
    keys = (iso["year"].astype(int) * 100 + iso["week"].astype(int)).to_numpy()
    mask = keys < cur_key
    if not mask.any():
        return None
    last_key = keys[mask].max()
    wk = df1d[keys == last_key]
    if len(wk) < 4:
        return None
    return float(wk["high"].max()), float(wk["low"].min())


def build_levels(data: dict, rng: Range, impulse: Impulse | None, now: pd.Timestamp, cfg) -> list[Level]:
    lv: list[Level] = []
    if rng.valid:
        lv.append(Level(rng.high, "range_edge", "Range High (1H)", "1h", _w(cfg, "range_edge")))
        lv.append(Level(rng.low, "range_edge", "Range Low (1H)", "1h", _w(cfg, "range_edge")))
    mr = monday_range(data["1h"], now)
    if mr:
        suffix = "" if mr[2] else " (berjalan)"
        lv.append(Level(mr[0], "monday", f"Monday High{suffix}", "1h", _w(cfg, "monday")))
        lv.append(Level(mr[1], "monday", f"Monday Low{suffix}", "1h", _w(cfg, "monday")))
    pdl = prev_day(data["1d"])
    if pdl:
        lv.append(Level(pdl[0], "prev_day", "Prev Day High", "1d", _w(cfg, "prev_day")))
        lv.append(Level(pdl[1], "prev_day", "Prev Day Low", "1d", _w(cfg, "prev_day")))
    pwl = prev_week(data["1d"], now)
    if pwl:
        lv.append(Level(pwl[0], "prev_week", "Prev Week High", "1d", _w(cfg, "prev_week")))
        lv.append(Level(pwl[1], "prev_week", "Prev Week Low", "1d", _w(cfg, "prev_week")))
    # FVG 4H + 1H (tepi terdekat ke harga)
    for tf, kind in (("4h", "fvg_4h"), ("1h", "fvg_1h")):
        a = last_atr(data[tf])
        if not np.isfinite(a):
            continue
        for g in find_fvgs(data[tf], a, cfg.levels.fvg_min_gap_atr):
            if g["dir"] == "bull":
                lv.append(Level(g["high"], kind, f"FVG bull {tf}", tf, _w(cfg, kind)))
            else:
                lv.append(Level(g["low"], kind, f"FVG bear {tf}", tf, _w(cfg, kind)))
    # Fibonacci dari impuls terakhir
    if impulse is not None and impulse.intact:
        for r, price in impulse.fibs.items():
            key = f"fib_{r}"
            lv.append(Level(float(price), key, f"Fib {r} ({impulse.direction})", "1h", _w(cfg, key)))
    # EMA dinamis
    e20 = float(ema(data["1h"]["close"], 20).iloc[-1])
    e50 = float(ema(data["4h"]["close"], 50).iloc[-1])
    lv.append(Level(e20, "ema", "EMA20 1H", "1h", _w(cfg, "ema")))
    lv.append(Level(e50, "ema", "EMA50 4H", "4h", _w(cfg, "ema")))
    # Pivot HTF (4H dan 1D)
    for tf in ("4h", "1d"):
        ph, pl = pivots(data[tf], 3)
        for _, p in ph[-3:]:
            lv.append(Level(p, "htf_pivot", f"Pivot High {tf}", tf, _w(cfg, "htf_pivot")))
        for _, p in pl[-3:]:
            lv.append(Level(p, "htf_pivot", f"Pivot Low {tf}", tf, _w(cfg, "htf_pivot")))
    return [x for x in lv if np.isfinite(x.price) and x.price > 0]


def confluence(price: float, levels: list[Level], tol: float, exclude_self: bool = True) -> tuple[float, list[Level]]:
    """Jumlah bobot level lain di sekitar `price` (dalam toleransi `tol` harga absolut)."""
    near = [x for x in levels if abs(x.price - price) <= tol]
    if exclude_self and near:
        closest = min(near, key=lambda x: abs(x.price - price))
        if abs(closest.price - price) < tol * 0.2:  # level itu sendiri
            near = [x for x in near if x is not closest]
    # satu bobot per jenis (hindari menghitung dobel level kembar)
    seen: dict[str, Level] = {}
    for x in near:
        if x.kind not in seen or x.weight > seen[x.kind].weight:
            seen[x.kind] = x
    use = list(seen.values())
    return float(sum(x.weight for x in use)), use


def compute_impulse(data: dict, cfg) -> Impulse | None:
    a = last_atr(data["1h"])
    if not np.isfinite(a):
        return None
    return last_impulse(data["1h"], a, cfg)
