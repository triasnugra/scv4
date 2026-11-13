"""Gate 6 [E]: konfirmasi. Tidak pernah menggantikan trigger.

- volume_spike      : lonjakan volume pada sweep/break
- wick_rejection    : sumbu penolakan di level
- orderbook_wall    : dinding order book mendukung arah entry (opsional, jika data ada)
- obv_bias          : OBV 1D searah (HANYA untuk koin volume tinggi, [E])
- rsi_divergence    : divergensi RSI 1H (bobot kecil, opsional)
- btc_alignment     : altcoin tidak melawan musim BTC
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import obv, rsi, vol_ratio
from .structure import pivots
from .triggers import Trigger


def orderbook_wall(book, trig: Trigger, cfg) -> dict | None:
    """Cek dinding order book di sisi pendukung (bid utk long, ask utk short) dekat zona entry-stop."""
    if not book:
        return None
    bids, asks = book
    side = bids if trig.direction == "long" else asks
    if not side:
        return None
    sizes = np.array([q for _, q in side], dtype=float)
    med = float(np.median(sizes)) if sizes.size else 0.0
    if med <= 0:
        return None
    mult = float(cfg.confirmations.orderbook_wall_mult)
    tol = float(cfg.confirmations.orderbook_wall_tol_pct) / 100.0
    lo, hi = sorted((trig.stop, trig.entry * (1 + tol if trig.direction == "long" else 1 - tol)))
    walls = [(p, q) for p, q in side if lo <= p <= hi and q >= mult * med]
    if not walls:
        return {"ok": False, "note": "tidak ada dinding di zona entry-stop"}
    p, q = max(walls, key=lambda x: x[1])
    return {"ok": True, "note": f"dinding {q / med:.1f}x median di {p:g}"}


def obv_bias(df1d: pd.DataFrame, direction: str, cfg) -> dict:
    lb = int(cfg.confirmations.obv_lookback_days)
    o = obv(df1d)
    if len(o) <= lb + 1:
        return {"ok": False, "note": "data OBV kurang"}
    slope = float(o.iloc[-1] - o.iloc[-1 - lb])
    ok = slope > 0 if direction == "long" else slope < 0
    return {"ok": bool(ok), "note": "OBV 1D searah" if ok else "OBV 1D berlawanan"}


def rsi_divergence(df1h: pd.DataFrame, direction: str, cfg) -> dict:
    n = int(cfg.confirmations.rsi_len)
    r = rsi(df1h["close"], n)
    d = df1h.iloc[-120:].reset_index(drop=True)
    rr = r.iloc[-120:].reset_index(drop=True)
    ph, pl = pivots(d, 3)
    if direction == "long" and len(pl) >= 2:
        (i1, p1), (i2, p2) = pl[-2], pl[-1]
        ok = p2 < p1 and rr.iloc[i2] > rr.iloc[i1]
        return {"ok": bool(ok), "note": "divergensi bullish RSI 1H" if ok else "tidak ada divergensi bullish"}
    if direction == "short" and len(ph) >= 2:
        (i1, p1), (i2, p2) = ph[-2], ph[-1]
        ok = p2 > p1 and rr.iloc[i2] < rr.iloc[i1]
        return {"ok": bool(ok), "note": "divergensi bearish RSI 1H" if ok else "tidak ada divergensi bearish"}
    return {"ok": False, "note": "pivot kurang"}


def gather(symbol: str, trig: Trigger, data: dict, book, btc_season: str | None, cfg) -> dict:
    """Kumpulkan konfirmasi untuk satu trigger. Return {'items': {...}, 'count': n}."""
    items: dict[str, dict] = {}
    d = trig.direction

    if "volume_spike" in trig.features:
        items["volume_spike"] = {"ok": True, "note": "volume > rata-rata pada sweep/break"}
    else:
        vr = float(vol_ratio(data["15m"]).iloc[-3:].max())
        items["volume_spike"] = {"ok": vr >= cfg.confirmations.volume_spike_mult, "note": f"vol 15m terakhir {vr:.1f}x"}

    items["wick_rejection"] = {"ok": "wick_rejection" in trig.features, "note": "sumbu penolakan di level"}

    wall = orderbook_wall(book, trig, cfg)
    if wall is not None:
        items["orderbook_wall"] = wall

    if symbol in cfg.obv_symbols:
        items["obv_bias"] = obv_bias(data["1d"], d, cfg)

    items["rsi_divergence"] = rsi_divergence(data["1h"], d, cfg)

    if symbol != "BTC" and btc_season:
        aligned = (btc_season == "NEUTRAL_RANGE") or (
            (d == "long" and btc_season == "LONG_SEASON") or (d == "short" and btc_season == "SHORT_SEASON")
        )
        items["btc_alignment"] = {"ok": bool(aligned), "note": f"musim BTC: {btc_season}"}

    count = sum(1 for v in items.values() if v.get("ok"))
    return {"items": items, "count": count}
