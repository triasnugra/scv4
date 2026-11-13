"""Pipeline keputusan scalping (Gate 0-9). Gagal di gate mana pun => NO_TRADE / WAIT + alasan."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import confirm as confirm_mod
from .config import is_major
from .indicators import last_atr
from .levels import Level, build_levels, compute_impulse, confluence
from .risk import check_risk, management_plan, position_size
from .structure import Range, detect_range, location, season as calc_season
from .triggers import ACTIVE, FAILED, MISSED, PENDING_STATUSES, Trigger, scan_triggers

LONG_SCALP, SHORT_SCALP, WAIT, NO_TRADE = "LONG_SCALP", "SHORT_SCALP", "WAIT", "NO_TRADE"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- Gate 0
def gate0(data: dict, now: pd.Timestamp, cfg) -> dict:
    reasons: list[str] = []
    for tf, minb in cfg.gate0_data.min_bars.items():
        if tf not in data or len(data[tf]) < minb:
            reasons.append(f"data {tf} kurang (<{minb} candle)")
    if reasons:
        return {"status": "FAIL", "note": "; ".join(reasons)}
    df15 = data["15m"]
    last_close_time = df15["time"].iloc[-1] + pd.Timedelta(minutes=15)
    if now - last_close_time > pd.Timedelta(minutes=15 * int(cfg.gate0_data.max_stale_bars)):
        reasons.append("data 15m basi")
    for tf in ("15m", "1h", "4h", "1d"):
        if data[tf][["open", "high", "low", "close", "volume"]].isna().any().any():
            reasons.append(f"ada NaN di data {tf}")
    qv = float((df15["close"] * df15["volume"]).tail(96).sum())
    if qv < cfg.gate0_data.min_quote_volume_24h:
        reasons.append(f"likuiditas rendah (vol 24j ~{qv / 1e6:.1f}M USD)")
    return {"status": "FAIL" if reasons else "PASS", "note": "; ".join(reasons), "quote_volume_24h": qv}


# ---------------------------------------------------------------- Gate 1
def gate1(data: dict, now: pd.Timestamp, cfg) -> dict:
    c = cfg.gate1_context
    notes: list[str] = []
    size_mult = 1.0
    edge_only = False
    status = "PASS"
    for w in c.stand_aside_windows or []:
        s, e = pd.Timestamp(w["start"]), pd.Timestamp(w["end"])
        s = s.tz_localize("UTC") if s.tzinfo is None else s
        e = e.tz_localize("UTC") if e.tzinfo is None else e
        if s <= now <= e:
            return {"status": "STAND_ASIDE", "size_mult": 0.0, "edge_only": False,
                    "notes": [f"jendela stand-aside: {w.get('label', 'event')}"]}
    df15, df1d = data["15m"], data["1d"]
    w24 = df15.tail(96)
    move24 = (float(w24["high"].max()) - float(w24["low"].min())) / float(w24["low"].min()) * 100.0
    shock = move24 >= c.shock_move_pct
    if not shock:
        for k in (1, 2):
            r = df1d.iloc[-k]
            rng_pct = (float(r["high"]) - float(r["low"])) / float(r["low"]) * 100.0
            closed_at = r["time"] + pd.Timedelta(days=1)
            if rng_pct >= c.shock_move_pct and (now - closed_at) <= pd.Timedelta(hours=float(c.shock_cooldown_hours)):
                shock = True
    if shock:
        if c.post_shock_policy == "stand_aside":
            return {"status": "STAND_ASIDE", "size_mult": 0.0, "edge_only": False,
                    "notes": ["post-shock (pump/dump besar): tunggu 24-48 jam"]}
        edge_only = True
        size_mult *= c.reduced_size_mult
        status = "REDUCE"
        notes.append("post-shock: hanya T1 di tepi range, ukuran dikurangi")
    if now.weekday() == 0 and c.monday_range_policy == "reduce":
        size_mult *= c.monday_size_mult
        status = "REDUCE"
        notes.append("Monday range masih terbentuk: ukuran dikurangi, maksimal 1-2 trade/jam")
    vol24 = float(w24["volume"].sum())
    med_day = float(df1d["volume"].tail(30).median())
    if med_day > 0 and vol24 / med_day < c.low_liquidity_ratio:
        size_mult *= c.reduced_size_mult
        status = "REDUCE"
        notes.append("likuiditas tipis (volume 24j < median harian)")
    return {"status": status, "size_mult": size_mult, "edge_only": edge_only, "notes": notes}


# ------------------------------------------------------- direction policy
def direction_policy(trig: Trigger, season_name: str, rng: Range, entry_pct: float | None, cfg) -> dict:
    """Return {allowed, counter_trend, reason}."""
    d = trig.direction
    counter = False
    if season_name == "LONG_SEASON" and d == "short":
        counter = True
    elif season_name == "SHORT_SEASON" and d == "long":
        counter = True
    if counter:
        if not cfg.gate2_season.allow_counter_trend:
            return {"allowed": False, "counter_trend": True, "reason": "melawan tren utama (counter-trend dimatikan)"}
        if trig.type not in ("T1", "T2"):
            return {"allowed": False, "counter_trend": True, "reason": "counter-trend hanya boleh via T1/T2"}
    mid_lo, mid_hi = cfg.gate3_range.mid_zone
    if rng.valid and entry_pct is not None and np.isfinite(entry_pct):
        if mid_lo <= entry_pct <= mid_hi:
            return {"allowed": False, "counter_trend": counter, "reason": f"entry di tengah range ({entry_pct:.0%})"}
        if season_name == "NEUTRAL_RANGE":
            if d == "long" and entry_pct > mid_hi:
                return {"allowed": False, "counter_trend": counter, "reason": "range netral: long hanya di sisi bawah"}
            if d == "short" and entry_pct < mid_lo:
                return {"allowed": False, "counter_trend": counter, "reason": "range netral: short hanya di sisi atas"}
    elif season_name == "NEUTRAL_RANGE":
        return {"allowed": False, "counter_trend": counter, "reason": "tren netral tanpa range valid (price action kotor)"}
    return {"allowed": True, "counter_trend": counter, "reason": ""}


# ---------------------------------------------------------------- scoring
def score_candidate(trig: Trigger, season_name: str, counter: bool, btc_opposite: bool, rng: Range,
                    entry_pct: float | None, conf_w: float, conf: dict, risk: dict, g1: dict, symbol: str, cfg) -> dict:
    w = cfg.scoring.weights
    if counter:
        trend = 0.25
    elif season_name == "NEUTRAL_RANGE":
        trend = 0.5
    else:
        trend = 1.0
    if btc_opposite:
        trend *= 0.85

    if rng.valid and entry_pct is not None and np.isfinite(entry_pct):
        edge_dist = min(abs(entry_pct), abs(entry_pct - 1.0))
        loc = 1.0 - _clamp(edge_dist / 0.5)
    else:
        loc = 0.45  # tanpa range valid, lokasi kurang terdefinisi
    if trig.type == "T3":
        loc = max(loc, 0.8)

    conf_s = _clamp(conf_w / cfg.levels.confluence_target)

    base = cfg.scoring.trigger_base.get(trig.type, 0.5)
    bonus = {"volume_spike": 0.15, "wick_rejection": 0.10, "double_deviation": 0.15, "three_tap": 0.10, "ema20>ema50": 0.05}
    q = base + sum(bonus.get(f, 0.0) for f in trig.features)
    q = _clamp(q) * (1.0 if trig.status == ACTIVE else 0.9)

    confirm_s = _clamp(conf["count"] / 3.0)

    max_stop = float(cfg.risk.max_stop_pct["majors" if is_major(cfg, symbol) else "alts"])
    rr_s = 0.5 * _clamp(risk.get("rr_tp2", 0.0) / 3.0) + 0.5 * _clamp(1.0 - risk["stop_pct"] / max_stop)
    if risk.get("synthetic"):
        rr_s *= 0.85

    ctx = 1.0 if g1["status"] == "PASS" else 0.5
    parts = {"trend": trend, "location": loc, "confluence": conf_s, "trigger": q, "confirmation": confirm_s, "rr": rr_s, "context": ctx}
    total = sum(float(w[k]) * v for k, v in parts.items())
    return {"score": round(total, 1), "parts": {k: round(v, 3) for k, v in parts.items()}}


# --------------------------------------------------------------- scenarios
def build_scenarios(rng: Range, season_name: str, levels: list[Level], price: float, cfg) -> list[dict]:
    out: list[dict] = []
    if rng.valid:
        rl, rh = rng.low, rng.high
        long_dev = {"side": "long", "type": "T1",
                    "text": f"Di atas {rl:g} -> bias long scalp. Aktivasi: harga menyapu di bawah {rl:g} lalu close 15m kembali di atas, entry di retest. Invalidasi: close 15m di bawah ekstrem sapuan."}
        short_dev = {"side": "short", "type": "T1",
                     "text": f"Di bawah {rh:g} -> bias short scalp. Aktivasi: harga menyapu di atas {rh:g} lalu close 15m kembali di bawah, entry di retest. Invalidasi: close 15m di atas ekstrem sapuan."}
        long_bo = {"side": "long", "type": "T2",
                   "text": f"Close 1H di atas {rh:g} dengan volume + 2 candle hold -> long di retest {rh:g}. Invalidasi: close 1H kembali di bawah {rh:g}."}
        short_bd = {"side": "short", "type": "T2",
                    "text": f"Close 1H di bawah {rl:g} dengan volume + 2 candle hold -> short di retest {rl:g}. Invalidasi: close 1H kembali di atas {rl:g}."}
        if season_name == "LONG_SEASON":
            out = [long_dev, long_bo]
        elif season_name == "SHORT_SEASON":
            out = [short_dev, short_bd]
        else:
            out = [long_dev, short_dev]
    else:
        below = sorted([x for x in levels if x.price < price and x.weight >= 0.7], key=lambda x: -x.price)
        above = sorted([x for x in levels if x.price > price and x.weight >= 0.7], key=lambda x: x.price)
        if season_name in ("LONG_SEASON", "NEUTRAL_RANGE") and below:
            x = below[0]
            out.append({"side": "long", "type": "T1/T3",
                        "text": f"Tunggu harga ke {x.label} ({x.price:g}). Long scalp hanya jika ada sapuan + reclaim atau reaksi fib 0.75 di sana."})
        if season_name in ("SHORT_SEASON", "NEUTRAL_RANGE") and above:
            x = above[0]
            out.append({"side": "short", "type": "T1/T3",
                        "text": f"Tunggu harga ke {x.label} ({x.price:g}). Short scalp hanya jika ada sapuan + reclaim ke bawah atau reaksi fib di sana."})
    for s in out:
        s["allowed"] = True
    return out[:2]


# ------------------------------------------------------------------ engine
def analyze(symbol: str, data: dict, now: pd.Timestamp, cfg, btc_season: str | None = None,
            state: dict | None = None, book=None) -> dict:
    state = state or {"trades_today": 0, "r_today": 0.0, "loss_streak": 0, "last_loss_time": None}
    res: dict = {
        "symbol": symbol, "timestamp": now.isoformat(), "decision": NO_TRADE, "season": None, "regime": None,
        "location": {}, "range": {}, "trigger": {"type": "NONE", "status": "NONE"}, "levels": {},
        "confirmations": {}, "score": 0.0, "score_parts": {}, "gates": {}, "reasons": [], "invalidated_if": [],
        "size": {}, "management": {}, "scenarios": [], "near_miss": [], "price": None,
    }
    # G0
    g0 = gate0(data, now, cfg)
    res["gates"]["G0"] = {"status": g0["status"], "note": g0["note"]}
    if g0["status"] != "PASS":
        res["reasons"].append("G0: " + g0["note"])
        return res
    price = float(data["15m"]["close"].iloc[-1])
    res["price"] = price
    atr15, atr1h, atr1d = last_atr(data["15m"]), last_atr(data["1h"]), last_atr(data["1d"])
    res["atr"] = {"15m": atr15, "1h": atr1h, "1d": atr1d}

    # G1
    g1 = gate1(data, now, cfg)
    res["gates"]["G1"] = {"status": g1["status"], "note": "; ".join(g1["notes"])}
    if g1["status"] == "STAND_ASIDE":
        res["decision"] = NO_TRADE
        res["reasons"].append("G1: " + "; ".join(g1["notes"]))
        return res

    # G2
    sea = calc_season(data["1d"], data["4h"], cfg)
    res["season"] = sea["season"]
    res["season_detail"] = sea
    res["gates"]["G2"] = {"status": "INFO", "note": f"{sea['season']} (skor {sea['score']:+.0f})"}

    # G3
    rng = detect_range(data["1h"], cfg)
    loc = location(rng, price, cfg)
    res["range"] = rng.to_dict()
    res["location"] = loc
    res["regime"] = "RANGING" if rng.valid else "TRENDING"
    res["gates"]["G3"] = {"status": "PASS" if loc["zone"] != "MID" else "FAIL",
                          "note": f"zona {loc['zone']}" + (f" ({loc['pct_of_range']:.0%})" if loc["pct_of_range"] is not None else "")}
    mid_note = "G3: harga di tengah range (no-man's land): tidak ada edge" if loc["zone"] == "MID" else ""

    # G4
    impulse = compute_impulse(data, cfg)
    levels = build_levels(data, rng, impulse, now, cfg)
    res["gates"]["G4"] = {"status": "INFO", "note": f"{len(levels)} level"}
    res["key_levels"] = [x.to_dict() for x in sorted(levels, key=lambda x: abs(x.price - price))[:12]]
    res["scenarios"] = build_scenarios(rng, sea["season"], levels, price, cfg)

    # macro support/resistance [E]: jangan short di support kuat
    n = int(cfg.gate2_season.macro_lookback_days)
    macro_lo, macro_hi = float(data["1d"]["low"].tail(n).min()), float(data["1d"]["high"].tail(n).max())

    # G5
    triggers = scan_triggers(data, levels, impulse, cfg)
    res["gates"]["G5"] = {"status": "PASS" if any(t.status in PENDING_STATUSES or t.status == ACTIVE for t in triggers) else "FAIL",
                          "note": f"{sum(1 for t in triggers if t.status == ACTIVE)} aktif, "
                                  f"{sum(1 for t in triggers if t.status in PENDING_STATUSES)} menunggu"}
    for t in triggers:
        if t.status in (FAILED, MISSED) and "tanpa volume" not in t.notes:
            res["near_miss"].append(f"{t.type} {t.direction} @ {t.level_label or round(t.level, 6)}: {t.notes}")
    res["near_miss"] = res["near_miss"][:6]

    live = [t for t in triggers if t.status == ACTIVE or t.status in PENDING_STATUSES]
    if not live:
        if mid_note:
            res["reasons"].append(mid_note)
        res["reasons"].append("G5: tidak ada trigger yang terkonfirmasi (tanpa trigger = tanpa trade)")
        res["gates"]["G6"] = res["gates"]["G7"] = res["gates"]["G8"] = {"status": "SKIP", "note": "tidak ada trigger"}
        return res

    # batas harian [C]
    lim = cfg.risk.limits
    limit_fail = ""
    if state["trades_today"] >= lim.max_trades_per_day:
        limit_fail = f"batas {lim.max_trades_per_day} trade/hari tercapai"
    elif state["r_today"] <= -float(lim.max_daily_loss_r):
        limit_fail = f"rugi harian {state['r_today']:.1f}R mencapai batas"
    elif state["loss_streak"] >= lim.loss_streak_cooldown and state.get("last_loss_time") is not None:
        if now - pd.Timestamp(state["last_loss_time"]) < pd.Timedelta(minutes=float(lim.cooldown_minutes)):
            limit_fail = f"cooldown setelah {state['loss_streak']} loss beruntun"

    cands: list[dict] = []
    fails: list[str] = []
    for trig in live:
        tag = f"{trig.type} {trig.direction} @ {trig.level_label or round(trig.level, 6)}"
        entry_pct = rng.pct(trig.entry) if rng.valid else None
        pol = direction_policy(trig, sea["season"], rng, entry_pct, cfg)
        if not pol["allowed"]:
            fails.append(f"{tag}: {pol['reason']}")
            continue
        if g1["edge_only"] and not (trig.type == "T1" and rng.valid and entry_pct is not None
                                    and (entry_pct <= cfg.gate3_range.edge_zone or entry_pct >= 1 - cfg.gate3_range.edge_zone)):
            fails.append(f"{tag}: post-shock hanya T1 di tepi range")
            continue
        if trig.direction == "short" and cfg.gate2_season.block_short_at_macro_support and price - macro_lo <= cfg.gate2_season.macro_zone_atr * atr1d:
            fails.append(f"{tag}: short di support makro")
            continue
        btc_opposite = bool(symbol != "BTC" and btc_season and (
            (trig.direction == "long" and btc_season == "SHORT_SEASON") or (trig.direction == "short" and btc_season == "LONG_SEASON")))
        # G6
        conf = confirm_mod.gather(symbol, trig, data, book, btc_season, cfg)
        if conf["count"] < cfg.confirmations.min_confirmations:
            fails.append(f"{tag}: konfirmasi kurang ({conf['count']})")
            continue
        # G7
        rk = check_risk(trig, levels, atr15, symbol, cfg)
        if not rk["ok"]:
            fails.append(f"{tag}: " + "; ".join(rk["reasons"]))
            continue
        tol = cfg.levels.confluence_tol_atr * atr1h
        conf_w, conf_used = confluence(trig.entry, levels, tol)
        sc = score_candidate(trig, sea["season"], pol["counter_trend"], btc_opposite, rng, entry_pct, conf_w, conf, rk, g1, symbol, cfg)
        if trig.direction == "long" and macro_hi - price <= cfg.gate2_season.macro_zone_atr * atr1d:
            sc["score"] = round(sc["score"] * 0.9, 1)
        cands.append({"trig": trig, "pol": pol, "conf": conf, "risk": rk, "score": sc, "btc_opposite": btc_opposite,
                      "conf_used": conf_used})

    res["gates"]["G6"] = {"status": "PASS" if cands else "FAIL", "note": f"{len(cands)} kandidat lolos"}
    if not cands:
        res["gates"]["G7"] = {"status": "FAIL", "note": "semua kandidat gugur"}
        res["gates"]["G8"] = {"status": "SKIP", "note": ""}
        if mid_note:
            res["reasons"].append(mid_note)
        res["reasons"].extend(fails[:5] or ["G5/G6/G7: kandidat tidak lolos"])
        return res

    best = max(cands, key=lambda c: c["score"]["score"])
    trig: Trigger = best["trig"]
    rk, sc, conf = best["risk"], best["score"], best["conf"]
    res["gates"]["G7"] = {"status": "FAIL" if limit_fail else "PASS", "note": limit_fail or f"stop {rk['stop_pct']:.2f}%, RR {rk['rr_tp1']:.1f}/{rk['rr_tp2']:.1f}"}

    need = float(cfg.scoring.trade_threshold) + (float(cfg.gate2_season.counter_trend_extra_score) if best["pol"]["counter_trend"] else 0.0)
    if limit_fail:
        res["reasons"].append("G7: " + limit_fail)
        decision = NO_TRADE
    elif trig.status == ACTIVE and sc["score"] >= need:
        decision = LONG_SCALP if trig.direction == "long" else SHORT_SCALP
    elif sc["score"] >= cfg.scoring.wait_threshold:
        decision = WAIT
    else:
        decision = NO_TRADE
    res["gates"]["G8"] = {"status": "PASS" if decision in (LONG_SCALP, SHORT_SCALP) else ("WAIT" if decision == WAIT else "FAIL"),
                          "note": f"skor {sc['score']:.0f} (butuh {need:.0f})"}

    size_mult = g1["size_mult"] * (cfg.gate2_season.counter_trend_size_mult if best["pol"]["counter_trend"] else 1.0)
    if best["btc_opposite"]:
        size_mult *= cfg.gate2_season.btc_opposite_size_mult
    d = 1 if trig.direction == "long" else -1
    res.update({
        "decision": decision,
        "trigger": {**trig.to_dict(), "limit_order": trig.status != ACTIVE, "counter_trend": best["pol"]["counter_trend"]},
        "levels": {
            "entry": trig.entry, "stop": trig.stop, "tp1": rk["tp1"], "tp2": rk["tp2"],
            "tp1_label": rk["tp1_label"], "tp2_label": rk["tp2_label"], "synthetic_tp": rk["synthetic"],
            "stop_pct": round(rk["stop_pct"], 3), "rr_tp1": round(rk["rr_tp1"], 2), "rr_tp2": round(rk["rr_tp2"], 2),
        },
        "confirmations": conf["items"],
        "score": sc["score"], "score_parts": sc["parts"],
        "size": position_size(trig.entry, trig.stop, size_mult, cfg),
        "management": management_plan(trig, rk, cfg),
        "confluence": [x.label for x in best["conf_used"]],
        "invalidated_if": [
            f"close 15m {'di bawah' if d == 1 else 'di atas'} {trig.stop:g}",
            "level kunci hilang / musim tren berbalik",
            "BTC kehilangan level kunci (untuk altcoin)",
        ],
    })
    if decision == WAIT:
        res["reasons"].append(f"{trig.type} {trig.direction}: {trig.notes} (skor {sc['score']:.0f})")
    elif decision == NO_TRADE and not res["reasons"]:
        res["reasons"].append(f"skor {sc['score']:.0f} < ambang {cfg.scoring.wait_threshold}")
    else:
        res["reasons"].append(f"{trig.type} {trig.direction}: {trig.notes}")
    return res
