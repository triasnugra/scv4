"""Tes logika inti: struktur, trigger (long & short simetris), risiko, simulasi trade."""
import numpy as np
import pandas as pd

from tests.helpers import cfg
from scalp.indicators import last_atr
from scalp.risk import net_rr, pick_targets, position_size, simulate_trade
from scalp.structure import detect_range, location, pivots
from scalp.synth import mid_range_scenario, sweep_reclaim_scenario
from scalp.triggers import ACTIVE, FAILED, MISSED, PENDING_RETEST, Trigger, classify, flip, t1, t2


def _candles(rows, start="2026-01-01 00:00"):
    t = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame({"time": t, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1.0})


def test_pivots_basic():
    df = _candles([(1, 2, 1, 1.5), (1.5, 3, 1.4, 2), (2, 5, 1.9, 4), (4, 4, 2, 3), (3, 3.5, 1.2, 2), (2, 2.5, 1.1, 1.5),
                   (1.5, 2.2, 1.0, 2.0), (2.0, 3, 1.8, 2.8)])
    ph, pl = pivots(df, 2)
    assert any(abs(p - 5) < 1e-9 for _, p in ph)


def test_range_detected_and_location():
    data, now, _ = sweep_reclaim_scenario("long")
    c = cfg()
    r = detect_range(data["1h"], c)
    assert r.valid and r.high > r.low
    assert location(r, r.low, c)["zone"] == "RL"
    assert location(r, r.high, c)["zone"] == "RH"
    assert location(r, r.mid, c)["zone"] == "MID"


def test_mid_range_scenario_is_mid():
    data, now = mid_range_scenario()
    c = cfg()
    r = detect_range(data["1h"], c)
    if r.valid:
        assert location(r, float(data["15m"]["close"].iloc[-1]), c)["zone"] in ("MID", "OTHER")


def test_t1_long_sweep_reclaim():
    data, now, edge = sweep_reclaim_scenario("long")
    c = cfg()
    r = detect_range(data["1h"], c)
    tr = t1(data["15m"], r.low, "long", c)
    assert tr is not None and tr.type == "T1" and tr.direction == "long"
    assert tr.status in (ACTIVE, PENDING_RETEST)
    assert tr.stop < tr.entry == r.low
    assert "volume_spike" in tr.features


def test_t1_short_is_mirror():
    data, now, edge = sweep_reclaim_scenario("short")
    c = cfg()
    r = detect_range(data["1h"], c)
    tr = t1(data["15m"], r.high, "short", c)
    assert tr is not None and tr.direction == "short"
    assert tr.status in (ACTIVE, PENDING_RETEST)
    assert tr.stop > tr.entry == r.high


def test_t1_no_sweep_means_none():
    data, now = mid_range_scenario()
    c = cfg()
    # level jauh di bawah harga: tidak ada sapuan
    price = float(data["15m"]["close"].iloc[-1])
    assert t1(data["15m"], price * 0.9, "long", c) is None


def test_t1_sweep_without_reclaim_fails_or_pends():
    data, now, edge = sweep_reclaim_scenario("long")
    c = cfg()
    df = data["15m"].copy()
    # paksa 4 candle terakhir close di bawah level => tidak ada reclaim yang bertahan
    r = detect_range(data["1h"], c)
    L = r.low
    for i in range(1, 5):
        idx = df.index[-i]
        df.loc[idx, ["open", "high", "low", "close"]] = [L * 0.995, L * 0.996, L * 0.99, L * 0.993]
    tr = t1(df, L, "long", c)
    assert tr is None or tr.status in (FAILED, "PENDING_RECLAIM")


def test_classify_dont_chase():
    c = cfg()
    assert classify(100.0, 100.0, 99.0, 1.0, c) == ACTIVE
    assert classify(100.9, 100.0, 99.0, 1.0, c) == PENDING_RETEST
    assert classify(103.0, 100.0, 99.0, 1.0, c) == MISSED
    assert classify(98.9, 100.0, 99.0, 1.0, c) == FAILED


def test_flip_involution():
    data, now, _ = sweep_reclaim_scenario("long")
    df = data["15m"].tail(50).reset_index(drop=True)
    ff = flip(flip(df))
    assert np.allclose(df[["open", "high", "low", "close"]].to_numpy(), ff[["open", "high", "low", "close"]].to_numpy())


def test_t2_breakout_retest_long():
    c = cfg()
    base = 100.0
    rows = []
    rng = np.random.default_rng(0)
    for i in range(120):  # range di bawah 101
        o = base + rng.normal(0, 0.15)
        cl = base + rng.normal(0, 0.15)
        rows.append((o, max(o, cl) + 0.1, min(o, cl) - 0.1, cl))
    L = 101.0
    # breakout bervolume lalu hold lalu retest
    seq = [(100.8, 101.8, 100.7, 101.6), (101.6, 102.0, 101.4, 101.8), (101.8, 102.0, 101.5, 101.7), (101.7, 101.9, 101.1, 101.25)]
    rows += seq
    df = _candles(rows)
    df["time"] = pd.date_range("2026-01-01", periods=len(df), freq="1h", tz="UTC")
    df.loc[df.index[-4], "volume"] = 10.0
    tr = t2(df, L, "long", c)
    assert tr is not None and tr.type == "T2"
    assert tr.status in (ACTIVE, PENDING_RETEST)
    assert tr.stop < L


def test_t2_failed_breakout():
    c = cfg()
    rng = np.random.default_rng(1)
    rows = []
    for i in range(120):
        o, cl = 100 + rng.normal(0, 0.15), 100 + rng.normal(0, 0.15)
        rows.append((o, max(o, cl) + 0.1, min(o, cl) - 0.1, cl))
    rows += [(100.8, 101.8, 100.7, 101.6), (101.6, 101.7, 100.2, 100.5)]  # close kembali di bawah level
    df = _candles(rows)
    df["time"] = pd.date_range("2026-01-01", periods=len(df), freq="1h", tz="UTC")
    df.loc[df.index[-2], "volume"] = 10.0
    tr = t2(df, 101.0, "long", c)
    assert tr is not None and tr.status == FAILED


# ----------------------------------------------------------------- risk
def test_net_rr_includes_costs():
    c = cfg()
    gross = abs(102 - 100) / abs(100 - 99)
    assert net_rr(100, 99, 102, "long", c) < gross


def test_position_size_caps_leverage():
    c = cfg()
    s = position_size(100.0, 99.95, 1.0, c)  # stop sangat rapat => leverage besar => dibatasi
    assert s["leverage_effective"] <= c.account.max_leverage_effective
    assert s["leverage_capped"] is True


def test_pick_targets_structural_then_synthetic():
    from scalp.levels import Level
    c = cfg()
    tr = Trigger("T1", "long", ACTIVE, 100.0, 99.0, 100.0)
    lv = [Level(101.0, "prev_day", "dekat", "1d", 0.8), Level(101.5, "prev_day", "PDH", "1d", 0.8), Level(102.9, "range_edge", "RH", "1h", 1.0)]
    tg = pick_targets(tr, lv, 0.3, "ETH", c)
    # 101.0 ditolak (R:R bersih < 1 setelah biaya); TP1=101.5, TP2=102.9
    assert tg["tp1"] == 101.5 and tg["tp2"] == 102.9 and tg["synthetic"] is False
    tg2 = pick_targets(tr, [], 0.3, "ETH", c)
    assert tg2["synthetic"] is True and tg2["tp2"] > tg2["tp1"] > 100.0


def _sim(rows, direction="long", **kw):
    c = cfg()
    df = _candles(rows)
    start = df["time"].iloc[0]
    return simulate_trade(df, direction, 100.0, 99.0, 101.5, 103.0, start, c)


def test_simulate_stop_first_when_same_candle():
    out = _sim([(100, 102, 98.5, 100)])  # menyentuh stop dan TP1 bersamaan => stop
    assert out["status"] == "SL" and out["r"] < -1.0 and out["closed"]


def test_simulate_tp1_then_breakeven():
    out = _sim([(100, 101.6, 99.5, 101), (101, 101.2, 99.9, 100.0), (100, 100.1, 99.9, 100.0)])
    # candle 2 tidak menyentuh BE (low 99.9 < 100? entry=100 => low<=100 menyentuh BE)
    assert out["status"] == "TP1_BE" and out["closed"]
    assert out["r"] > 0  # parsial TP1 masih positif setelah biaya


def test_simulate_tp2():
    out = _sim([(100, 101.6, 100.5, 101), (101, 103.2, 100.8, 103)])
    assert out["status"] == "TP2" and out["r"] > 1.5


def test_simulate_short_mirror():
    c = cfg()
    df = _candles([(100, 100.2, 98.4, 98.6), (98.6, 98.9, 96.8, 97.0)])
    out = simulate_trade(df, "short", 100.0, 101.0, 98.5, 97.0, df["time"].iloc[0], c)
    assert out["status"] == "TP2" and out["closed"]


def test_simulate_open_when_nothing_happens():
    out = _sim([(100, 100.5, 99.6, 100.2)])
    assert out["status"] == "OPEN" and not out["closed"]
