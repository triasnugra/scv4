"""Tes engine (pipeline gate), tracker, data (mock jaringan), laporan, dan backtest."""
import json
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from tests.helpers import cfg
from scalp import data as data_mod
from scalp.backtest import run_backtest
from scalp.engine import LONG_SCALP, NO_TRADE, SHORT_SCALP, WAIT, analyze
from scalp.report import clean, write_site
from scalp.synth import mid_range_scenario, sweep_reclaim_scenario
from scalp.tracker import add_signal, daily_state, summarize

VALID = {LONG_SCALP, SHORT_SCALP, WAIT, NO_TRADE}


def test_engine_long_scenario_produces_coherent_plan():
    data, now, _ = sweep_reclaim_scenario("long")
    res = analyze("ETH", data, now, cfg())
    assert res["decision"] in VALID
    assert set(res["gates"]) >= {"G0", "G1", "G2", "G3", "G4", "G5"}
    if res["decision"] in (LONG_SCALP, WAIT):
        lv = res["levels"]
        assert lv["stop"] < lv["entry"] < lv["tp1"] < lv["tp2"]
        assert lv["stop_pct"] <= 5.0  # batas altcoin
        assert lv["rr_tp2"] >= 2.0 - 1e-6 or lv["synthetic_tp"]
        assert res["size"]["leverage_effective"] <= cfg().account.max_leverage_effective
        assert res["invalidated_if"]


def test_engine_mid_range_never_trades():
    data, now = mid_range_scenario()
    res = analyze("ETH", data, now, cfg())
    assert res["decision"] in (NO_TRADE, WAIT)
    assert res["decision"] != LONG_SCALP and res["decision"] != SHORT_SCALP
    assert res["reasons"]


def test_engine_stale_data_fails_g0():
    data, now, _ = sweep_reclaim_scenario("long")
    res = analyze("ETH", data, now + pd.Timedelta(hours=3), cfg())
    assert res["decision"] == NO_TRADE and res["gates"]["G0"]["status"] == "FAIL"


def test_engine_low_liquidity_symbol_rejected():
    data, now, _ = sweep_reclaim_scenario("long")
    c = cfg(gate0_data={"min_quote_volume_24h": 10**12})
    res = analyze("ETH", data, now, c)
    assert res["decision"] == NO_TRADE and "likuiditas" in res["gates"]["G0"]["note"]


def test_engine_stand_aside_window():
    data, now, _ = sweep_reclaim_scenario("long")
    c = cfg(gate1_context={"stand_aside_windows": [{"start": str(now - pd.Timedelta(hours=1)), "end": str(now + pd.Timedelta(hours=1)), "label": "FOMC"}]})
    res = analyze("ETH", data, now, c)
    assert res["decision"] == NO_TRADE and "FOMC" in res["reasons"][0]


def test_engine_daily_limit_blocks_trade():
    data, now, _ = sweep_reclaim_scenario("long")
    state = {"trades_today": 99, "r_today": 0.0, "loss_streak": 0, "last_loss_time": None}
    res = analyze("ETH", data, now, cfg(), state=state)
    assert res["decision"] in (NO_TRADE,)  # tidak boleh LONG/SHORT/WAIT saat batas harian tercapai


def test_engine_scenarios_present():
    data, now, _ = sweep_reclaim_scenario("long")
    res = analyze("ETH", data, now, cfg())
    assert 1 <= len(res["scenarios"]) <= 2


# --------------------------------------------------------------- tracker
def _fake_result(symbol="BTC", entry=100.0):
    return {"decision": "LONG_SCALP", "symbol": symbol, "score": 80,
            "trigger": {"direction": "long", "type": "T1", "level_label": "RL"},
            "levels": {"entry": entry, "stop": entry - 1, "tp1": entry + 1.5, "tp2": entry + 3}}


def test_tracker_dedupe_and_state():
    h = {"signals": []}
    now = pd.Timestamp("2026-11-11 12:00", tz="UTC")
    assert add_signal(h, _fake_result(), now) is True
    assert add_signal(h, _fake_result(), now + pd.Timedelta(minutes=30)) is False
    st = daily_state(h, now + pd.Timedelta(minutes=31))
    assert st["trades_today"] == 1
    h["signals"][0].update(status="SL", r=-1.1, closed_at=(now + pd.Timedelta(hours=1)).isoformat())
    st = daily_state(h, now + pd.Timedelta(hours=2))
    assert st["loss_streak"] == 1 and st["r_today"] < 0
    s = summarize(h)
    assert s["closed"] == 1 and s["win_rate"] == 0.0


def test_tracker_ignores_non_trade():
    h = {"signals": []}
    r = _fake_result()
    r["decision"] = "WAIT"
    assert add_signal(h, r, pd.Timestamp("2026-11-11 12:00", tz="UTC")) is False


# ------------------------------------------------------------------ data
class FakeProvider(data_mod.Provider):
    name = "fake"
    max_chunk = 1000

    def __init__(self, df_by_tf, fail=False):
        super().__init__()
        self.df_by_tf, self.fail = df_by_tf, fail

    def candles(self, base, quote, tf, limit, end_ms=None):
        if self.fail:
            raise data_mod.DataError("diblokir")
        df = self.df_by_tf[tf]
        if end_ms is not None:
            df = df[df["time"] <= pd.Timestamp(end_ms, unit="ms", tz="UTC")]
        return df.tail(limit).reset_index(drop=True)


def test_drop_unclosed_removes_open_candle():
    now = pd.Timestamp("2026-11-11 12:07", tz="UTC")
    df = pd.DataFrame({"time": pd.to_datetime(["2026-11-11 11:45", "2026-11-11 12:00"], utc=True),
                       "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    out = data_mod.drop_unclosed(df, "15m", now)
    assert len(out) == 1  # candle 12:00-12:15 belum tertutup


def test_fetch_symbol_falls_back_to_next_provider():
    d, now, _ = sweep_reclaim_scenario("long")
    c = cfg(data={"providers": ["binance_vision", "okx"], "bars": {"5m": 300, "15m": 300, "1h": 300, "4h": 200, "1d": 100}})
    providers = {"binance_vision": FakeProvider(d, fail=True), "okx": FakeProvider(d)}
    with mock.patch.object(data_mod, "make_provider", lambda name, cfg: providers[name]):
        out, prov = data_mod.fetch_symbol("BTC", c, now)
    assert prov.name == "fake" and set(out) == {"5m", "15m", "1h", "4h", "1d"}
    assert len(out["15m"]) == 300


def test_fetch_symbol_all_fail_raises():
    d, now, _ = sweep_reclaim_scenario("long")
    c = cfg(data={"providers": ["binance_vision"]})
    with mock.patch.object(data_mod, "make_provider", lambda name, cfg: FakeProvider(d, fail=True)):
        try:
            data_mod.fetch_symbol("BTC", c, now)
            assert False, "harus error"
        except data_mod.DataError as exc:
            assert "semua provider gagal" in str(exc)


# ---------------------------------------------------------------- report
def test_clean_handles_nan_and_numpy():
    out = clean({"a": float("nan"), "b": np.float64(1.5), "c": np.int64(3), "d": [np.nan]})
    assert out == {"a": None, "b": 1.5, "c": 3, "d": [None]}
    json.dumps(out, allow_nan=False)


def test_write_site_creates_valid_files():
    with tempfile.TemporaryDirectory() as td:
        write_site(td, {"generated_at": "2026-11-11T12:00:00+00:00", "mode": "demo", "providers": [], "results": [],
                        "signals": [], "stats": {}, "x": float("nan")})
        html = (Path(td) / "index.html").read_text(encoding="utf-8")
        assert "__DATA__" not in html and "Mesin Analisis Scalping" in html
        json.loads((Path(td) / "data.json").read_text(encoding="utf-8"))
        assert (Path(td) / ".nojekyll").exists()


# -------------------------------------------------------------- backtest
def test_backtest_runs_without_lookahead_errors():
    data, now, _ = sweep_reclaim_scenario("long")
    rep = run_backtest("ETH", data, cfg(), days=2, step=2)
    assert {"total_signals", "closed", "total_r", "per_trigger"} <= set(rep)
    for s in rep["signals"]:
        assert s["stop"] != s["entry"]
