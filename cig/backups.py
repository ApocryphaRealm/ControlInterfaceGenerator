"""Backups before file-changing actions, and undo (plan 2.6 item 5)."""
from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Iterable

from . import config


def _root() -> Path:
    d = config.home() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def take(app: str, action: str, paths: Iterable[str]) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    bid = f"{stamp}-{re.sub(r'[^a-z0-9]+', '-', (app + '-' + action).lower()).strip('-')}"[:96]
    d = _root() / bid
    d.mkdir(parents=True)
    manifest = []
    for i, p in enumerate(paths):
        src = Path(p)
        entry = {"path": str(src), "existed": src.is_file()}
        if src.is_file():
            dst = d / f"{i:03d}-{src.name}"
            shutil.copy2(src, dst)
            entry["copy"] = dst.name
        manifest.append(entry)
    (d / "manifest.json").write_text(json.dumps({"app": app, "action": action, "files": manifest}, indent=2),
                                     encoding="utf-8")
    return bid


def undo(backup_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9-]+", backup_id or ""):
        return {"ok": False, "error": "bad backup id"}
    d = _root() / backup_id
    mf = d / "manifest.json"
    if not mf.exists():
        return {"ok": False, "error": f"no backup {backup_id}"}
    data = json.loads(mf.read_text(encoding="utf-8"))
    restored, removed = [], []
    for e in data["files"]:
        target = Path(e["path"])
        if e.get("copy"):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / e["copy"], target)
            restored.append(str(target))
        elif not e["existed"] and target.exists():
            target.unlink()                      # the action created it; undo removes it
            removed.append(str(target))
    return {"ok": True, "restored": restored, "removed": removed}


def list_backups(n: int = 20) -> list[str]:
    return sorted((p.name for p in _root().iterdir() if p.is_dir()), reverse=True)[:n]
