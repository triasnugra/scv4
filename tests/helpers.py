import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scalp.config import load_config  # noqa: E402


def cfg(**over):
    base = {"gate0_data": {"min_quote_volume_24h": 1000}}
    for k, v in over.items():
        base.setdefault(k, {}).update(v)
    return load_config(overrides=base)
