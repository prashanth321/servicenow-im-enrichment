"""
Simple JSON-file persistence for dashboard in-memory stores.

Each service gets its own JSON file under ``data/``.  On import the file
is loaded (if it exists); every mutation calls ``save()`` to flush.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)

_locks: dict[str, Lock] = {}

# Maximum number of incident keys per store before LRU-style eviction
MAX_KEYS: int = 500


def _lock_for(name: str) -> Lock:
    if name not in _locks:
        _locks[name] = Lock()
    return _locks[name]


def load(name: str) -> Any:
    """Load JSON data from ``data/{name}.json``.  Returns ``{}`` if missing."""
    path = _DATA_DIR / f"{name}.json"
    if not path.exists():
        return {}
    with _lock_for(name):
        return json.loads(path.read_text(encoding="utf-8"))


def save(name: str, data: Any) -> None:
    """Persist *data* to ``data/{name}.json``."""
    path = _DATA_DIR / f"{name}.json"
    with _lock_for(name):
        path.write_text(json.dumps(data, default=str), encoding="utf-8")


def evict_oldest(store: dict, max_keys: int = MAX_KEYS) -> None:
    """Remove the oldest keys from *store* if it exceeds *max_keys*.

    Relies on Python 3.7+ insertion-order dicts — the first keys
    inserted are the oldest and will be evicted first.
    """
    while len(store) > max_keys:
        oldest_key = next(iter(store))
        del store[oldest_key]
