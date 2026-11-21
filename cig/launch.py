"""Start and close programs safely (plan 2.6 item 10, past-mistakes 7623 / 3712).

launch: refused by the safety layer like any write (presence, deny list); always at normal integrity - when CIG itself
        runs elevated the program is started through Explorer, which runs unelevated. Waits for the program's window
        (also when an app-execution alias such as notepad.exe hands over to another process).
close:  graceful only - WM_CLOSE to the program's windows; never TerminateProcess.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from typing import Optional

import psutil
import win32con
import win32gui

from . import actionlog, presence
from .detect import windows_of
from .policy import Policy, Request, WRITE, decide


def _elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _windowed_pids(name: str) -> set[int]:
    out = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info["name"] or "").lower() == name.lower() and windows_of(p.info["pid"]):
                out.add(p.info["pid"])
        except psutil.Error:
            continue
    return out


def launch(exe: str, args: list[str], policy: Optional[Policy] = None, confirm: Optional[str] = None,
           wait_s: float = 25.0) -> dict:
    policy = policy or Policy.load()
    name = os.path.basename(exe)
    pres = presence.read()
    dec = decide(Request(app=name, action="launch", kind=WRITE, confirm=confirm), pres, policy)
    entry = {"app": name, "action": "launch", "kind": WRITE, "args": args, "presence": pres.as_dict(),
             "policy": dec.as_dict(), "confirm": confirm}
    if not dec.allowed:
        entry.update(ok=False, refused=True, reason=dec.reason)
        return {**entry, "log_id": actionlog.write(entry)}
    before = _windowed_pids(name)
    t0 = time.time()
    try:
        if _elevated():
            subprocess.Popen(["explorer.exe", exe], close_fds=True)        # Explorer starts it unelevated
            entry["via"] = "explorer (CIG is elevated)"
        else:
            subprocess.Popen([exe, *args], close_fds=True, creationflags=subprocess.DETACHED_PROCESS
                             | subprocess.CREATE_NEW_PROCESS_GROUP, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            entry["via"] = "direct (CIG is not elevated)"
    except OSError as e:
        entry.update(ok=False, refused=False, reason=f"could not start: {e}")
        return {**entry, "log_id": actionlog.write(entry)}
    pid = None
    while time.time() - t0 < wait_s:
        new = _windowed_pids(name) - before
        if new:
            pid = min(new)
            break
        time.sleep(0.4)
    if pid is None:
        entry.update(ok=False, refused=False, reason=f"no new window for {name} within {wait_s:g}s")
    else:
        h = windows_of(pid)
        entry.update(ok=True, refused=False, pid=pid, title=win32gui.GetWindowText(h[0]) if h else "",
                     waited_s=round(time.time() - t0, 1))
    return {**entry, "log_id": actionlog.write(entry)}


def close(pid: int, wait_s: float = 10.0) -> dict:
    """Ask the program to close (WM_CLOSE). Never forces. A save prompt stays open and is reported."""
    hs = windows_of(pid)
    for h in hs:
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except win32gui.error:
            pass
    t0 = time.time()
    while time.time() - t0 < wait_s and psutil.pid_exists(pid):
        time.sleep(0.3)
    gone = not psutil.pid_exists(pid)
    res = {"ok": gone, "pid": pid, "closed": gone}
    if not gone:
        res["still_open"] = [win32gui.GetWindowText(h) for h in windows_of(pid)]
    actionlog.write({"action": "close_app", "kind": WRITE, "pid": pid, **res})
    return res
