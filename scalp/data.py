"""Pengambilan data pasar (REST publik, tanpa API key).

Provider: binance_vision (data-api.binance.vision, spot), okx (perpetual swap), bybit (linear).
Satu provider dipakai untuk SEMUA timeframe satu simbol supaya harga tidak tercampur sumber.

CATATAN: sebagian exchange memblokir IP tertentu (mis. HTTP 451/403 dari runner di AS).
Karena itu ada urutan fallback di config.yaml -> data.providers.
"""
from __future__ import annotations

import time
from typing import Iterable

import pandas as pd
import requests

TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
COLS = ["time", "open", "high", "low", "close", "volume"]
UA = {"User-Agent": "scalp-engine/1.0 (+github-actions)"}


class DataError(RuntimeError):
    pass


def tf_delta(tf: str) -> pd.Timedelta:
    return pd.Timedelta(seconds=TF_SECONDS[tf])


def _frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLS)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    for c in COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return df


def drop_unclosed(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    """Buang candle yang belum tertutup (hanya candle tertutup yang dipakai)."""
    if df.empty:
        return df
    closed = df["time"] + tf_delta(tf) <= now
    return df.loc[closed].reset_index(drop=True)


def _get(url: str, params: dict, timeout: float, retries: int = 2):
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = DataError(f"HTTP {r.status_code} {url}")
            if r.status_code in (403, 451):  # diblokir wilayah: jangan buang waktu
                break
        except requests.RequestException as exc:
            last = exc
        time.sleep(0.8 * (i + 1))
    raise DataError(str(last))


class Provider:
    name = "base"
    max_chunk = 500

    def __init__(self, timeout: float = 15, overrides: dict | None = None):
        self.timeout = timeout
        self.overrides = overrides or {}

    def sym(self, base: str, quote: str) -> str:
        return self.overrides.get(base) or self._sym(base, quote)

    def _sym(self, base: str, quote: str) -> str:
        raise NotImplementedError

    def candles(self, base: str, quote: str, tf: str, limit: int, end_ms: int | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def orderbook(self, base: str, quote: str, depth: int = 100) -> tuple[list, list]:
        raise NotImplementedError


class BinanceVision(Provider):
    name = "binance_vision"
    max_chunk = 1000
    BASE = "https://data-api.binance.vision/api/v3"

    def _sym(self, base, quote):
        return f"{base}{quote}"

    def candles(self, base, quote, tf, limit, end_ms=None):
        params = {"symbol": self.sym(base, quote), "interval": tf, "limit": min(limit, self.max_chunk)}
        if end_ms:
            params["endTime"] = int(end_ms)
        data = _get(f"{self.BASE}/klines", params, self.timeout)
        rows = [(d[0], d[1], d[2], d[3], d[4], d[5]) for d in data]
        return _frame(rows)

    def orderbook(self, base, quote, depth=100):
        d = _get(f"{self.BASE}/depth", {"symbol": self.sym(base, quote), "limit": depth}, self.timeout)
        return [(float(p), float(q)) for p, q in d["bids"]], [(float(p), float(q)) for p, q in d["asks"]]


class OKX(Provider):
    name = "okx"
    max_chunk = 100
    BASE = "https://www.okx.com/api/v5/market"
    BAR = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}

    def _sym(self, base, quote):
        return f"{base}-{quote}-SWAP"

    def candles(self, base, quote, tf, limit, end_ms=None):
        inst = self.sym(base, quote)
        if end_ms is None:
            url = f"{self.BASE}/candles"
            params = {"instId": inst, "bar": self.BAR[tf], "limit": min(limit, 300)}
        else:
            url = f"{self.BASE}/history-candles"
            params = {"instId": inst, "bar": self.BAR[tf], "limit": min(limit, 100), "after": int(end_ms) + 1}
        data = _get(url, params, self.timeout)
        if data.get("code") not in (None, "0"):
            raise DataError(f"OKX error {data.get('code')} {data.get('msg')}")
        rows = []
        for d in data.get("data", []):
            vol = d[6] if len(d) > 6 and d[6] not in ("", None) else d[5]
            rows.append((d[0], d[1], d[2], d[3], d[4], vol))
        return _frame(rows)

    def orderbook(self, base, quote, depth=100):
        d = _get(f"{self.BASE}/books", {"instId": self.sym(base, quote), "sz": depth}, self.timeout)
        book = d["data"][0]
        return [(float(x[0]), float(x[1])) for x in book["bids"]], [(float(x[0]), float(x[1])) for x in book["asks"]]


class Bybit(Provider):
    name = "bybit"
    max_chunk = 1000
    BASE = "https://api.bybit.com/v5/market"
    INT = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

    def _sym(self, base, quote):
        return f"{base}{quote}"

    def candles(self, base, quote, tf, limit, end_ms=None):
        params = {
            "category": "linear",
            "symbol": self.sym(base, quote),
            "interval": self.INT[tf],
            "limit": min(limit, self.max_chunk),
        }
        if end_ms:
            params["end"] = int(end_ms)
        data = _get(f"{self.BASE}/kline", params, self.timeout)
        if data.get("retCode") not in (None, 0):
            raise DataError(f"Bybit error {data.get('retCode')} {data.get('retMsg')}")
        rows = [(d[0], d[1], d[2], d[3], d[4], d[5]) for d in data["result"]["list"]]
        return _frame(rows)

    def orderbook(self, base, quote, depth=100):
        d = _get(
            f"{self.BASE}/orderbook",
            {"category": "linear", "symbol": self.sym(base, quote), "limit": min(depth, 200)},
            self.timeout,
        )["result"]
        return [(float(p), float(q)) for p, q in d["b"]], [(float(p), float(q)) for p, q in d["a"]]


PROVIDERS = {"binance_vision": BinanceVision, "okx": OKX, "bybit": Bybit}


def make_provider(name: str, cfg) -> Provider:
    ov = (cfg.data.get("symbol_overrides") or {}).get(name) or {}
    return PROVIDERS[name](timeout=cfg.data.timeout_sec, overrides=dict(ov))


def fetch_bars(provider: Provider, base: str, quote: str, tf: str, bars: int) -> pd.DataFrame:
    """Ambil `bars` candle terbaru, paginasi mundur bila perlu."""
    frames: list[pd.DataFrame] = []
    end_ms: int | None = None
    got = 0
    guard = 0
    while got < bars and guard < 60:
        guard += 1
        need = bars - got
        df = provider.candles(base, quote, tf, min(need, provider.max_chunk), end_ms)
        if df.empty:
            break
        frames.append(df)
        got = len(pd.concat(frames).drop_duplicates("time"))
        earliest = int(df["time"].iloc[0].value // 1_000_000)
        new_end = earliest - 1
        if end_ms is not None and new_end >= end_ms:
            break
        end_ms = new_end
        if len(df) < min(need, provider.max_chunk) and len(df) < 50:
            break
    if not frames:
        raise DataError(f"tidak ada data {base} {tf} dari {provider.name}")
    out = pd.concat(frames).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return out.tail(bars).reset_index(drop=True)


def fetch_symbol(base: str, cfg, now: pd.Timestamp | None = None, tfs: Iterable[str] | None = None):
    """Ambil semua TF untuk satu simbol dari provider pertama yang berhasil penuh.

    Return: (data: dict[tf] -> DataFrame candle tertutup, provider)
    """
    now = now or pd.Timestamp.now(tz="UTC")
    tfs = list(tfs or cfg.data.bars.keys())
    errors: list[str] = []
    for pname in cfg.data.providers:
        try:
            prov = make_provider(pname, cfg)
            data = {}
            for tf in tfs:
                df = fetch_bars(prov, base, cfg.quote, tf, int(cfg.data.bars[tf]))
                data[tf] = drop_unclosed(df, tf, now)
            return data, prov
        except Exception as exc:  # noqa: BLE001 - lanjut ke provider berikutnya
            errors.append(f"{pname}: {exc}")
    raise DataError(f"{base}: semua provider gagal -> " + " | ".join(errors))


def fetch_orderbook(provider: Provider, base: str, cfg):
    try:
        return provider.orderbook(base, cfg.quote, 100)
    except Exception:  # noqa: BLE001 - order book opsional
        return None
