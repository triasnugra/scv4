"""Backtest: jalankan engine yang SAMA pada data historis, candle demi candle (tanpa look-ahead).

- Setiap langkah = penutupan candle 15m. Engine hanya melihat candle yang sudah tertutup pada saat itu.
- Trade disimulasikan dengan simulate_trade() (stop dulu bila bersamaan, biaya fee+slippage dihitung).
- Order book/heatmap tidak tersedia historis -> konfirmasi tersebut dilewati (skor lebih konservatif).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import TF_SECONDS, drop_unclosed, fetch_bars, make_provider, tf_delta
from .engine import analyze
from .structure import season as calc_season
from .tracker import OPEN_STATUSES, add_signal, daily_state, summarize
from .risk import simulate_trade

BARS_CAP = {"5m": 600, "15m": 500, "1h": 500, "4h": 300, "1d": 300}


def fetch_backtest_data(base: str, cfg, days: int, provider_name: str | None = None) -> dict:
    now = pd.Timestamp.now(tz="UTC")
    need = {"5m": days * 288 + 50, "15m": days * 96 + 600, "1h": days * 24 + 600, "4h": days * 6 + 300, "1d": days + 250}
    last_err = None
    for pname in ([provider_name] if provider_name else list(cfg.data.providers)):
        try:
            prov = make_provider(pname, cfg)
            return {tf: drop_unclosed(fetch_bars(prov, base, cfg.quote, tf, n), tf, now) for tf, n in need.items()}
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"gagal mengambil data backtest {base}: {last_err}")


class _AsOf:
    """Slice data as-of waktu t (hanya candle yang tertutup <= t)."""

    def __init__(self, data: dict):
        self.data = data
        self.close_times = {
            tf: (df["time"] + tf_delta(tf)).dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
            for tf, df in data.items()
        }

    def at(self, t: pd.Timestamp) -> dict:
        out = {}
        t64 = np.datetime64(t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t, "ns")
        for tf, df in self.data.items():
            ct = self.close_times[tf]
            idx = int(np.searchsorted(ct, t64, side="right"))
            lo = max(0, idx - BARS_CAP[tf] - 50)
            out[tf] = df.iloc[lo:idx].reset_index(drop=True)
        return out


def run_backtest(symbol: str, data: dict, cfg, btc_data: dict | None = None, days: int | None = None, step: int | None = None) -> dict:
    bt = cfg.backtest
    days = days or int(bt.days)
    step = step or int(bt.step)
    asof = _AsOf(data)
    btc_asof = _AsOf(btc_data) if (btc_data is not None and symbol != "BTC") else None
    df15 = data["15m"]
    n_steps = days * 96
    start_i = max(len(df15) - n_steps, 0)
    hist = {"signals": []}
    last_signal_i = -10**9
    for i in range(start_i, len(df15), step):
        t = df15["time"].iloc[i] + tf_delta("15m")
        d = asof.at(t)
        if any(len(d[tf]) < cfg.gate0_data.min_bars.get(tf, 1) for tf in ("15m", "1h", "4h", "1d")):
            continue
        # perbarui sinyal terbuka dengan candle 5m sampai t
        c5 = d["5m"]
        for s in hist["signals"]:
            if s["status"] in OPEN_STATUSES:
                out = simulate_trade(c5, s["direction"], s["entry"], s["stop"], s["tp1"], s["tp2"], pd.Timestamp(s["time"]), cfg)
                s["status"], s["r"] = out["status"], round(float(out["r"]), 3)
                s["closed_at"] = out["closed_at"].isoformat() if out["closed_at"] is not None else None
        if any(s["status"] in OPEN_STATUSES for s in hist["signals"]) and bt.max_open_per_symbol <= 1:
            continue
        if i - last_signal_i < int(bt.cooldown_bars):
            continue
        btc_season = None
        if btc_asof is not None:
            bd = btc_asof.at(t)
            if len(bd["1d"]) >= 60 and len(bd["4h"]) >= 100:
                btc_season = calc_season(bd["1d"], bd["4h"], cfg)["season"]
        state = daily_state(hist, t)
        res = analyze(symbol, d, t, cfg, btc_season=btc_season, state=state, book=None)
        if add_signal(hist, res, t):
            last_signal_i = i
            hist["signals"][-1]["time"] = t.isoformat()
    # tutup semua sisa dengan data lengkap
    full5 = data["5m"]
    for s in hist["signals"]:
        if s["status"] in OPEN_STATUSES:
            out = simulate_trade(full5, s["direction"], s["entry"], s["stop"], s["tp1"], s["tp2"], pd.Timestamp(s["time"]), cfg)
            s["status"], s["r"] = out["status"], round(float(out["r"]), 3)
            s["closed_at"] = out["closed_at"].isoformat() if out["closed_at"] is not None else None
    return report(hist, symbol, days)


def report(hist: dict, symbol: str, days: int) -> dict:
    sums = summarize(hist)
    closed = [s for s in hist["signals"] if s.get("closed_at")]
    wins = [s["r"] for s in closed if s["r"] > 0]
    losses = [-s["r"] for s in closed if s["r"] < 0]
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else None
    by: dict[str, dict] = {}
    for s in closed:
        k = s["trigger"]
        b = by.setdefault(k, {"n": 0, "r": 0.0, "wins": 0})
        b["n"] += 1
        b["r"] += s["r"]
        b["wins"] += 1 if s["r"] > 0 else 0
    per_trigger = {k: {"trades": v["n"], "total_r": round(v["r"], 2), "win_rate": round(v["wins"] / v["n"] * 100, 1),
                       "expectancy_r": round(v["r"] / v["n"], 3)} for k, v in by.items()}
    return {"symbol": symbol, "days": days, **sums, "profit_factor": None if pf is None else round(pf, 2),
            "per_trigger": per_trigger, "signals": hist["signals"]}


def print_report(rep: dict) -> None:
    print(f"\n=== BACKTEST {rep['symbol']} ({rep['days']} hari) ===")
    print(f"Sinyal: {rep['total_signals']} | selesai: {rep['closed']} | win rate: {rep['win_rate']}% | "
          f"total: {rep['total_r']}R | expectancy: {rep['expectancy_r']}R | PF: {rep['profit_factor']} | maxDD: {rep['max_drawdown_r']}R")
    for k, v in sorted(rep["per_trigger"].items()):
        print(f"  {k}: {v['trades']} trade, win {v['win_rate']}%, total {v['total_r']}R, exp {v['expectancy_r']}R")
    if not rep["closed"]:
        print("  (tidak ada trade selesai: NO_TRADE adalah hasil yang valid. Cek parameter bila terlalu sering.)")
