"""Loader konfigurasi YAML dengan akses atribut (cfg.gate3_range.lookback_bars)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


class Box(dict):
    """dict dengan akses atribut, rekursif."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def _box(obj: Any) -> Any:
    if isinstance(obj, dict):
        return Box({k: _box(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_box(v) for v in obj]
    return obj


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Box:
    """Muat config.yaml (default di root repo). `overrides` untuk tes/CLI."""
    p = Path(path) if path else DEFAULT_PATH
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if overrides:
        raw = _merge(raw, overrides)
    return _box(raw)


def is_major(cfg: Box, symbol: str) -> bool:
    return symbol in cfg.majors
