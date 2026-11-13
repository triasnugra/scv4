"""Tulis keluaran: data.json, history.json, index.html (dashboard statis untuk GitHub Pages)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

TEMPLATE = Path(__file__).resolve().parent / "web" / "index.template.html"


def clean(obj):
    """Ubah numpy/NaN/Timestamp menjadi JSON valid."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def write_site(out_dir: str | Path, payload: dict) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = clean(payload)
    text = json.dumps(payload, ensure_ascii=False)
    (out / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", text.replace("</", "<\\/"))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
