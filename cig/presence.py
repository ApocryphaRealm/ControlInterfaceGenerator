"""Is the person at the machine using it right now? (plan 2.6 item 2)

Two sources, most trustworthy first:
  1. The owner-input watcher's file (role `owner-real-input`): `last_real_input_epoch` counts only REAL keyboard /
     mouse / pad input (the watcher's low-level hooks drop injected input), `watcher_alive_epoch` is its heartbeat.
     Trusted only while the heartbeat is fresh (under WATCHER_STALE_MIN).
  2. Windows' GetLastInputInfo. It counts injected input too, so it can only make the answer MORE cautious.

Test seams (environment): CIG_OWNER_REAL_INPUT_FILE (or OWNER_REAL_INPUT_FILE), CIG_SYSTEM_IDLE_MIN ("none" = no
reading), CIG_FOREGROUND_PID ("none" = no foreground window), CIG_NOW (epoch seconds).
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

from . import config

WATCHER_STALE_MIN = 3.0


def now() -> float:
    seam = config.seam("CIG_NOW")
    return float(seam) if seam else time.time()


def _read_watcher() -> Optional[dict]:
    path = config.owner_input_file()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def system_idle_minutes() -> Optional[float]:
    seam = config.seam("CIG_SYSTEM_IDLE_MIN")
    if seam:
        return None if seam.lower() == "none" else float(seam)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    try:
        li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((tick - li.dwTime) & 0xFFFFFFFF) / 60000.0
    except (AttributeError, OSError):
        return None


def foreground_pid() -> Optional[int]:
    seam = config.seam("CIG_FOREGROUND_PID")
    if seam:
        return None if seam.lower() == "none" else int(seam)
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except (AttributeError, OSError):
        return None


def exe_of(pid: Optional[int]) -> str:
    seam = config.seam("CIG_FOREGROUND_EXE")
    if seam is not None:
        return seam
    if not pid:
        return ""
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:                                      # noqa: BLE001
        return ""


@dataclass
class Presence:
    idle_min: Optional[float]      # minutes since the last input we trust; None = unknown
    source: str                    # "watcher" | "system" | "unknown"
    foreground_pid: Optional[int]
    foreground_exe: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        if d["idle_min"] is not None:
            d["idle_min"] = round(d["idle_min"], 2)
        return d


def read() -> Presence:
    t = now()
    w = _read_watcher()
    fg = foreground_pid()
    fx = exe_of(fg)
    if w:
        try:
            alive = float(w.get("watcher_alive_epoch") or 0)
            last = float(w.get("last_real_input_epoch") or 0)
        except (TypeError, ValueError):
            alive = last = 0.0
        if alive and (t - alive) / 60.0 < WATCHER_STALE_MIN and last:
            return Presence(max(0.0, (t - last) / 60.0), "watcher", fg, fx)
    sys_idle = system_idle_minutes()
    if sys_idle is not None:
        return Presence(sys_idle, "system", fg, fx)
    return Presence(None, "unknown", fg, fx)
