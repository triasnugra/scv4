"""Gate 7 + Gate 9: invalidasi, target, R:R bersih biaya, ukuran posisi, simulasi trade.

Simulasi memakai asumsi KONSERVATIF: bila stop dan target tersentuh dalam candle yang sama,
dianggap stop lebih dulu.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import is_major
from .levels import Level
from .triggers import Trigger


def cost_pct(cfg) -> float:
    """Biaya round-trip (fee + slippage kedua sisi) sebagai fraksi harga."""
    a = cfg.account
    return 2.0 * (a.fee_bps + a.slippage_bps) / 10_000.0


def _side(cfg, key: str, symbol: str) -> float:
    return float(cfg.risk[key]["majors" if is_major(cfg, symbol) else "alts"])


def net_rr(entry: float, stop: float, target: float, direction: str, cfg) -> float:
    risk = abs(entry - stop)
    reward = abs(target - entry)
    cost = entry * cost_pct(cfg)
    if risk <= 0:
        return 0.0
    return (reward - cost) / (risk + cost)


def pick_targets(trig: Trigger, levels: list[Level], atr15: float, symbol: str, cfg) -> dict:
    """TP1 = level struktural pertama dengan R:R >= min; TP2 = berikutnya dengan R:R >= min. [E] logikanya."""
    d = 1 if trig.direction == "long" else -1
    entry, stop = trig.entry, trig.stop
    max_dist = entry * _side(cfg, "max_tp_pct", symbol) / 100.0
    min_dist = 0.5 * atr15
    cands = sorted(
        {round(x.price, 10): x for x in levels if d * (x.price - entry) >= min_dist and d * (x.price - entry) <= max_dist}.values(),
        key=lambda x: d * (x.price - entry),
    )
    tp1 = tp2 = None
    l1 = l2 = ""
    for lv in cands:
        if tp1 is None and net_rr(entry, stop, lv.price, trig.direction, cfg) >= cfg.risk.min_rr_tp1:
            tp1, l1 = lv.price, lv.label
            continue
        if tp1 is not None and net_rr(entry, stop, lv.price, trig.direction, cfg) >= cfg.risk.min_rr_tp2:
            tp2, l2 = lv.price, lv.label
            break
    synthetic = False
    risk = abs(entry - stop)
    if cfg.risk.allow_synthetic_tp:
        r1, r2 = cfg.risk.synthetic_tp_r
        if tp1 is None:
            tp1, l1, synthetic = entry + d * r1 * risk, f"{r1}R (sintetis)", True
        if tp2 is None:
            t2 = entry + d * max(r2, 0.0) * risk
            if d * (t2 - tp1) > 0:
                tp2, l2, synthetic = t2, f"{r2}R (sintetis)", True
    if tp1 is None or tp2 is None:
        return {}
    return {"tp1": tp1, "tp2": tp2, "tp1_label": l1, "tp2_label": l2, "synthetic": synthetic}


def check_risk(trig: Trigger, levels: list[Level], atr15: float, symbol: str, cfg) -> dict:
    """Gate 7. Return dict: ok, reasons, entry/stop/tp, stop_pct, rr."""
    reasons: list[str] = []
    entry, stop = trig.entry, trig.stop
    risk = abs(entry - stop)
    stop_pct = risk / entry * 100.0
    if (trig.direction == "long" and stop >= entry) or (trig.direction == "short" and stop <= entry):
        return {"ok": False, "reasons": ["stop berada di sisi yang salah"], "stop_pct": stop_pct}
    max_stop = _side(cfg, "max_stop_pct", symbol)
    if stop_pct > max_stop:
        reasons.append(f"stop {stop_pct:.2f}% > batas {max_stop:.1f}% (bukan scalp / itu swing)")
    if risk < cfg.risk.min_stop_atr15 * atr15:
        reasons.append("stop terlalu rapat (noise)")
    tg = pick_targets(trig, levels, atr15, symbol, cfg)
    if not tg:
        reasons.append("tidak ada target dengan R:R memadai")
        return {"ok": False, "reasons": reasons, "stop_pct": stop_pct}
    rr1 = net_rr(entry, stop, tg["tp1"], trig.direction, cfg)
    rr2 = net_rr(entry, stop, tg["tp2"], trig.direction, cfg)
    if rr1 < cfg.risk.min_rr_tp1:
        reasons.append(f"R:R TP1 {rr1:.2f} < {cfg.risk.min_rr_tp1}")
    if rr2 < cfg.risk.min_rr_tp2:
        reasons.append(f"R:R TP2 {rr2:.2f} < {cfg.risk.min_rr_tp2}")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "stop_pct": stop_pct,
        "rr_tp1": rr1,
        "rr_tp2": rr2,
        **tg,
    }


def position_size(entry: float, stop: float, size_mult: float, cfg) -> dict:
    """Ukuran posisi dari risiko; leverage = hasil hitung & dibatasi."""
    a = cfg.account
    risk_usd = a.equity_usd * (a.risk_pct / 100.0) * size_mult
    dist = abs(entry - stop)
    qty = risk_usd / dist if dist > 0 else 0.0
    notional = qty * entry
    lev = notional / a.equity_usd if a.equity_usd else 0.0
    capped = False
    if lev > a.max_leverage_effective:
        factor = a.max_leverage_effective / lev
        qty *= factor
        notional *= factor
        risk_usd *= factor
        lev = a.max_leverage_effective
        capped = True
    return {
        "risk_pct": round(a.risk_pct * size_mult, 4),
        "risk_usd": round(risk_usd, 4),
        "qty": float(f"{qty:.8g}"),
        "notional_usd": round(notional, 2),
        "leverage_effective": round(lev, 2),
        "leverage_capped": capped,
    }


def management_plan(trig: Trigger, tp: dict, cfg) -> dict:
    """Gate 9 [E]: TP1 parsial -> stop ke break-even; stop cadangan lebih rapat; time stop."""
    r = cfg.risk
    risk = abs(trig.entry - trig.stop)
    d = 1 if trig.direction == "long" else -1
    return {
        "entry_type": "LIMIT di level retest" if trig.status != "ACTIVE" else "LIMIT/MARKET setelah candle konfirmasi",
        "tp1_fraction": r.tp1_fraction,
        "move_stop_to_breakeven_after_tp1": r.move_stop_to_be_after_tp1,
        "tight_stop": round(trig.entry - d * r.tight_stop_fraction * risk, 8),
        "time_stop_hours": r.time_stop_hours,
        "reentry_max": 1,
        "rules": [
            "jangan geser stop menjauh",
            "jangan tahan scalp jadi swing",
            "keluar bila level kunci/bias berubah",
        ],
    }


# ------------------------------------------------------------- simulation
def simulate_trade(candles: pd.DataFrame, direction: str, entry: float, stop: float, tp1: float, tp2: float,
                   start: pd.Timestamp, cfg) -> dict:
    """Simulasikan satu trade pada candle (kolom time/open/high/low/close) SETELAH `start`.

    Return: {status, r, closed_at, closed}. Bila belum selesai: closed=False, status='OPEN'.
    r = hasil dalam kelipatan risiko (R), sudah dikurangi biaya.
    """
    d = 1 if direction == "long" else -1
    risk = abs(entry - stop)
    if risk <= 0:
        return {"status": "INVALID", "r": 0.0, "closed": True, "closed_at": None}
    frac = float(cfg.risk.tp1_fraction)
    cost_r = entry * cost_pct(cfg) / risk
    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk
    max_age = pd.Timedelta(hours=float(cfg.risk.time_stop_hours))
    seg = candles[candles["time"] >= start]
    phase = 0
    stop_cur = stop
    realized = 0.0
    for row in seg.itertuples(index=False):
        hi, lo, cl, t = float(row.high), float(row.low), float(row.close), row.time
        if d == 1:
            hit_stop = lo <= stop_cur
            hit_tp1, hit_tp2 = hi >= tp1, hi >= tp2
        else:
            hit_stop = hi >= stop_cur
            hit_tp1, hit_tp2 = lo <= tp1, lo <= tp2
        if phase == 0:
            if hit_stop:  # konservatif: stop dulu bila bersamaan
                return {"status": "SL", "r": -1.0 - cost_r, "closed": True, "closed_at": t}
            if hit_tp1:
                phase = 1
                realized = frac * rr1
                if cfg.risk.move_stop_to_be_after_tp1:
                    stop_cur = entry
                if hit_tp2:  # TP1 dan TP2 dalam satu candle: ambil TP1 saja dulu (konservatif)
                    pass
                continue
        else:
            if hit_stop:
                st = "TP1_BE" if cfg.risk.move_stop_to_be_after_tp1 else "TP1_SL"
                rem = 0.0 if cfg.risk.move_stop_to_be_after_tp1 else (-1.0)
                return {"status": st, "r": realized + (1 - frac) * rem - cost_r, "closed": True, "closed_at": t}
            if hit_tp2:
                return {"status": "TP2", "r": realized + (1 - frac) * rr2 - cost_r, "closed": True, "closed_at": t}
        if t - start >= max_age:  # time stop
            mark = d * (cl - entry) / risk
            if phase == 0:
                return {"status": "TIME", "r": mark - cost_r, "closed": True, "closed_at": t}
            return {"status": "TP1_TIME", "r": realized + (1 - frac) * mark - cost_r, "closed": True, "closed_at": t}
    return {"status": "OPEN" if phase == 0 else "TP1_OPEN", "r": realized, "closed": False, "closed_at": None}
