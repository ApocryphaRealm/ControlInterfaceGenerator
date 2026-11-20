"""Append-only JSON-lines action log (plan 2.6 item 8). Secrets are redacted before anything is written."""
from __future__ import annotations

import datetime
import json
import os
import threading
import uuid
from typing import Any

from . import config

_LOCK = threading.Lock()
SECRET_KEYS = {"password", "secret", "token", "pin", "passphrase", "api_key", "apikey", "credential"}


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<redacted>" if str(k).lower() in SECRET_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def write(entry: dict) -> str:
    log_id = uuid.uuid4().hex[:12]
    rec = {"log_id": log_id,
           "time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           **redact(entry)}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    path = config.log_file()
    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return log_id


def tail(n: int = 20) -> list[dict]:
    path = config.log_file()
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-max(1, min(int(n), 500)):]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
