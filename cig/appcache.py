"""Per-app cache (plan 2.5 "Discovery and caching"): cache/apps/<app-key>.json holds each element's locator and
fingerprint and the menu paths seen, so an element id from an earlier server run still resolves (exactly, or by
fingerprint) and menu paths are offered before the menus are opened again. The app key carries the program's version,
so a new version starts a new cache - nothing from an old version is trusted."""
from __future__ import annotations

import hashlib
import json
import re
import time

from . import config

SAVE_EVERY_S = 20.0
_last_save: dict[str, tuple[float, int]] = {}


def _path(key: str):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:80]
    return config.cache_dir() / f"{safe}-{hashlib.sha1(key.encode()).hexdigest()[:8]}.json"


def _read(key: str) -> dict:
    p = _path(key)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if data.get("key") == key else {}
    except (OSError, ValueError):
        return {}


def load_known(key: str) -> dict:
    return {eid: {"locator": e["locator"], "fingerprint": e["fingerprint"], "node": {}}
            for eid, e in (_read(key).get("elements") or {}).items()}


def load_menu_paths(key: str) -> list[str]:
    return list(_read(key).get("menu_paths") or [])


def save(key: str, snap: dict, force: bool = False) -> None:
    n = len(snap.get("known") or {})
    p = _path(key)
    last_t, last_n = _last_save.get(str(p), (0.0, -1))
    if not force and p.exists() and n == last_n and time.time() - last_t < SAVE_EVERY_S:
        return
    data = {"key": key, "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elements": {eid: {"locator": e["locator"], "fingerprint": e["fingerprint"]}
                         for eid, e in (snap.get("known") or {}).items()},
            "menu_paths": snap.get("menu_paths") or []}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _last_save[str(p)] = (time.time(), n)
