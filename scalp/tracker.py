"""Riwayat sinyal: simpan sinyal TRADE, lacak hasilnya (R), hitung batas harian.

history.json dibawa antar-run lewat GitHub Pages (workflow mengunduh versi sebelumnya).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .risk import simulate_trade

OPEN_STATUSES = {"OPEN", "TP1_OPEN"}


def load_history(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"signals": []}
    try:
        h = json.loads(p.read_text(encoding="utf-8"))
        h.setdefault("signals", [])
        return h
    except (json.JSONDecodeError, OSError):
        return {"signals": []}


def save_history(history: dict, path: str | Path, max_signals: int) -> None:
    history["signals"] = history["signals"][-max_signals:]
    Path(path).write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")


def update_open_signals(history: dict, data_by_symbol: dict, cfg) -> int:
    """Perbarui hasil sinyal yang masih terbuka memakai candle 5m terbaru. Return jumlah yang berubah."""
    changed = 0
    for sig in history["signals"]:
        if sig.get("status") not in OPEN_STATUSES:
            continue
        data = data_by_symbol.get(sig["symbol"])
        if not data or "5m" not in data:
            continue
        out = simulate_trade(data["5m"], sig["direction"], sig["entry"], sig["stop"], sig["tp1"], sig["tp2"],
                             pd.Timestamp(sig["time"]), cfg)
        new_status = out["status"]
        if new_status != sig["status"] or out["closed"]:
            changed += 1
        sig["status"] = new_status
        sig["r"] = round(float(out["r"]), 3)
        sig["closed_at"] = out["closed_at"].isoformat() if out["closed_at"] is not None else None
    return changed


def daily_state(history: dict, now: pd.Timestamp) -> dict:
    """Hitung batas harian: jumlah trade hari ini (UTC), R hari ini, loss beruntun, waktu loss terakhir."""
    day0 = now.normalize()
    today = [s for s in history["signals"] if pd.Timestamp(s["time"]) >= day0]
    r_today = sum(float(s.get("r", 0.0)) for s in today if s.get("status") not in OPEN_STATUSES)
    closed = sorted((s for s in history["signals"] if s.get("closed_at")), key=lambda s: s["closed_at"])
    streak, last_loss = 0, None
    for s in reversed(closed):
        if float(s.get("r", 0.0)) < 0:
            streak += 1
            last_loss = last_loss or s["closed_at"]
        else:
            break
    return {"trades_today": len(today), "r_today": float(r_today), "loss_streak": streak, "last_loss_time": last_loss}


def add_signal(history: dict, result: dict, now: pd.Timestamp) -> bool:
    """Catat keputusan LONG/SHORT_SCALP. Hindari duplikat (simbol+arah+level sama dalam 3 jam)."""
    if result["decision"] not in ("LONG_SCALP", "SHORT_SCALP"):
        return False
    trig, lv = result["trigger"], result["levels"]
    for s in history["signals"][-30:]:
        if (s["symbol"] == result["symbol"] and s["direction"] == trig["direction"]
                and abs(s["entry"] - lv["entry"]) / lv["entry"] < 0.002
                and now - pd.Timestamp(s["time"]) < pd.Timedelta(hours=3)):
            return False
    history["signals"].append({
        "id": f"{result['symbol']}-{int(now.timestamp())}",
        "symbol": result["symbol"], "direction": trig["direction"], "trigger": trig["type"],
        "level_label": trig.get("level_label", ""), "time": now.isoformat(),
        "entry": lv["entry"], "stop": lv["stop"], "tp1": lv["tp1"], "tp2": lv["tp2"],
        "score": result["score"], "status": "OPEN", "r": 0.0, "closed_at": None,
    })
    return True


def summarize(history: dict) -> dict:
    closed = [s for s in history["signals"] if s.get("closed_at")]
    rs = [float(s["r"]) for s in closed]
    n = len(rs)
    wins = sum(1 for r in rs if r > 0)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "total_signals": len(history["signals"]),
        "closed": n,
        "open": len(history["signals"]) - n,
        "win_rate": round(wins / n * 100, 1) if n else None,
        "total_r": round(sum(rs), 2),
        "expectancy_r": round(sum(rs) / n, 3) if n else None,
        "max_drawdown_r": round(mdd, 2),
    }
