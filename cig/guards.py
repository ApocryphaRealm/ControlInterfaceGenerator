"""System side-effect guards (found live 2026-11-20: a test Vortex on its own data folder still took over the nxm://
handler). A program's library entry (library/apps/*.json, "system_side_effects") lists the system keys it is known to
change; CIG exports them before launching it and restores them after it closes, then verifies the restore. A launch
whose guard cannot be taken is refused. Guards are kept on disk, so a later server run can still restore them."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from . import config
from .detect import app_entries


def _dir() -> Path:
    d = config.home() / "guards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def keys_for(exe: str) -> list[str]:
    name = os.path.basename(exe).lower()
    out = []
    for app in app_entries():
        if name in [x.lower() for x in app.get("exe", [])]:
            out += (app.get("system_side_effects") or {}).get("registry_keys", [])
    return out


def _reg(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["reg", *args], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)


def _lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    return sorted(line for line in text.splitlines() if line.strip())


def take(exe: str, tag: str) -> Optional[dict]:
    """Export every guarded key. Returns the guard record, or None when the program has no known side effects.
    Raises RuntimeError when a key cannot be exported (the caller refuses the launch)."""
    keys = keys_for(exe)
    if not keys:
        return None
    rec = {"exe": exe, "tag": tag, "keys": []}
    for i, k in enumerate(keys):
        q = _reg("query", k)
        f = _dir() / f"{tag}-{i}.reg"
        if q.returncode != 0:
            rec["keys"].append({"key": k, "existed": False})
            continue
        e = _reg("export", k, str(f), "/y")
        if e.returncode != 0 or not f.exists():
            raise RuntimeError(f"cannot export {k}: {e.stderr.strip()}")
        rec["keys"].append({"key": k, "existed": True, "file": str(f)})
    (_dir() / f"{tag}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def rename(tag: str, new_tag: str) -> None:
    p = _dir() / f"{tag}.json"
    if p.exists():
        p.rename(_dir() / f"{new_tag}.json")


def restore(tag: str) -> dict:
    p = _dir() / f"{tag}.json"
    if not p.exists():
        return {"guard": None}
    rec = json.loads(p.read_text(encoding="utf-8"))
    results = []
    for k in rec["keys"]:
        if not k["existed"]:
            if _reg("query", k["key"]).returncode == 0:
                _reg("delete", k["key"], "/f")
            ok = _reg("query", k["key"]).returncode != 0
            results.append({"key": k["key"], "restored": ok, "how": "removed (did not exist before)"})
            continue
        _reg("import", k["file"])
        check = Path(k["file"] + ".check")
        _reg("export", k["key"], str(check), "/y")
        ok = check.exists() and _lines(check) == _lines(Path(k["file"]))
        results.append({"key": k["key"], "restored": ok, "how": "re-imported the export taken before the launch"})
    if all(r["restored"] for r in results):
        p.rename(p.with_suffix(".restored.json"))
    return {"guard": tag, "keys": results, "all_restored": all(r["restored"] for r in results)}


def pending() -> list[str]:
    return [p.stem for p in _dir().glob("*.json") if not p.name.endswith(".restored.json")]
