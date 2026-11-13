"""CLI.

  python -m scalp.main analyze  --out site            # analisis live + dashboard (dipakai GitHub Actions)
  python -m scalp.main analyze  --out site --demo     # data sintetis (uji tampilan offline)
  python -m scalp.main backtest --symbol BTC --days 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .backtest import fetch_backtest_data, print_report, run_backtest
from .config import load_config
from .data import DataError, fetch_orderbook, fetch_symbol
from .engine import analyze
from .report import clean, write_site
from .structure import season as calc_season
from .synth import demo_data
from .tracker import add_signal, daily_state, load_history, save_history, summarize, update_open_signals


def _error_result(symbol: str, now: pd.Timestamp, msg: str) -> dict:
    return {
        "symbol": symbol, "timestamp": now.isoformat(), "decision": "NO_TRADE", "season": None, "regime": None,
        "location": {}, "range": {}, "trigger": {"type": "NONE", "status": "NONE"}, "levels": {}, "confirmations": {},
        "score": 0.0, "gates": {"G0": {"status": "FAIL", "note": msg}}, "reasons": ["G0: " + msg], "invalidated_if": [],
        "size": {}, "management": {}, "scenarios": [], "near_miss": [], "price": None,
    }


def cmd_analyze(args) -> int:
    cfg = load_config(args.config)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    hist_path = Path(args.history or (out_dir / "history.json"))
    history = load_history(hist_path)

    now = pd.Timestamp.now(tz="UTC")
    symbols = list(cfg.symbols)
    order = ["BTC"] + [s for s in symbols if s != "BTC"]  # BTC dulu: konteks musim utk altcoin

    datas: dict = {}
    books: dict = {}
    providers_used: set[str] = set()
    errors: dict[str, str] = {}
    if args.demo:
        demo, now = demo_data(order)
        datas.update(demo)
        providers_used.add("demo-sintetis")
    else:
        for s in order:
            try:
                d, prov = fetch_symbol(s, cfg, now)
                datas[s] = d
                providers_used.add(prov.name)
                if cfg.data.use_orderbook:
                    books[s] = fetch_orderbook(prov, s, cfg)
            except DataError as exc:
                errors[s] = str(exc)
                print(f"[WARN] {s}: {exc}", file=sys.stderr)

    update_open_signals(history, datas, cfg)
    state = daily_state(history, now)

    btc_season = None
    if "BTC" in datas:
        try:
            btc_season = calc_season(datas["BTC"]["1d"], datas["BTC"]["4h"], cfg)["season"]
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] musim BTC gagal: {exc}", file=sys.stderr)

    results = []
    for s in order:
        if s not in symbols:
            continue
        if s not in datas:
            results.append(_error_result(s, now, errors.get(s, "data tidak tersedia")))
            continue
        try:
            res = analyze(s, datas[s], now, cfg, btc_season=btc_season if s != "BTC" else None, state=state, book=books.get(s))
        except Exception as exc:  # noqa: BLE001 - satu simbol error jangan menjatuhkan semuanya
            print(f"[ERROR] {s}: {exc!r}", file=sys.stderr)
            res = _error_result(s, now, f"error engine: {exc!r}")
        if add_signal(history, res, now):
            state = daily_state(history, now)
        results.append(res)

    payload = {
        "version": __version__,
        "generated_at": now.isoformat(),
        "mode": "demo" if args.demo else "live",
        "providers": sorted(providers_used),
        "results": results,
        "signals": history["signals"],
        "stats": summarize(history),
        "errors": errors,
    }
    write_site(out_dir, payload)
    save_history(history, hist_path, int(cfg.history.max_signals))
    for r in results:
        print(f"{r['symbol']:>6}  {r['decision']:<11} {r.get('season') or '-':<14} skor {r.get('score', 0):>5.1f}  "
              f"{(r['reasons'] or [''])[0][:90]}")
    print(f"\nOutput: {out_dir}/index.html, data.json, history.json")
    # Gagal keras hanya jika SEMUA simbol gagal ambil data (supaya Actions menandai merah)
    if not args.demo and symbols and all(s in errors for s in symbols):
        return 2
    return 0


def cmd_backtest(args) -> int:
    cfg = load_config(args.config)
    days = args.days or int(cfg.backtest.days)
    if args.demo:
        from .synth import sweep_reclaim_scenario
        data, _, _ = sweep_reclaim_scenario("long")
        btc = None
    else:
        data = fetch_backtest_data(args.symbol, cfg, days, args.provider)
        btc = fetch_backtest_data("BTC", cfg, days, args.provider) if args.symbol != "BTC" else None
    rep = run_backtest(args.symbol, data, cfg, btc_data=btc, days=days, step=args.step)
    print_report(rep)
    if args.json:
        Path(args.json).write_text(json.dumps(clean(rep), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Detail: {args.json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scalp", description="Mesin analisis scalping crypto (logika Eliz + Claude)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analisis live + tulis dashboard")
    a.add_argument("--config", default=None)
    a.add_argument("--out", default="site")
    a.add_argument("--history", default=None, help="path history.json (default: <out>/history.json)")
    a.add_argument("--demo", action="store_true", help="pakai data sintetis (tanpa jaringan)")
    a.set_defaults(fn=cmd_analyze)
    b = sub.add_parser("backtest", help="backtest walk-forward")
    b.add_argument("--config", default=None)
    b.add_argument("--symbol", default="BTC")
    b.add_argument("--days", type=int, default=None)
    b.add_argument("--step", type=int, default=None, help="loncat N candle 15m per langkah (lebih cepat)")
    b.add_argument("--provider", default=None)
    b.add_argument("--json", default=None, help="simpan detail ke file JSON")
    b.add_argument("--demo", action="store_true")
    b.set_defaults(fn=cmd_backtest)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
