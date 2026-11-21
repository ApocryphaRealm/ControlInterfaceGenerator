"""In-process bridges (beyond UI Automation): a small piece of CIG running INSIDE a program CIG launched, reading the
framework's own object tree and acting through the framework's own properties - so a framework that publishes little
or nothing to accessibility (Avalonia's combo options and list items, Tk, Python-hosted FireMonkey) is still fully
reachable. How the code gets in is always an official, documented mechanism applied at launch, never injection into
a running process:
  dotnet   .NET startup hooks (DOTNET_STARTUP_HOOKS)        bridges/dotnet  -> Avalonia (WPF/WinForms later)
  python   a launch wrapper that starts the bridge first    bridges/python  -> tkinter, delphifmx
Each bridge writes {host, port, token, pid} to the channel file CIG named, listens on 127.0.0.1 only, and answers one
JSON line per request: ping / tree / act. Its tree is already in CIG's node format, so the same rules, locators and
safety layer apply; this adapter only carries messages."""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Optional

import psutil

from .. import config, locator as loc_mod
from .base import Adapter, AdapterError, Target

BRIDGES: dict[int, dict] = {}       # pid -> channel info, for programs CIG launched with a bridge
_LOCK = threading.Lock()


def bridge_dir() -> Path:
    """Where CIG writes bridge CHANNEL files (its own data folder, never next to the program)."""
    import os
    d = Path(os.environ.get("CIG_BRIDGE_CHANNELS") or (config.home() / "bridges"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    """Where the bridge FILES are: the .NET hook (dotnet/Cig.Bridge.DotNet.dll) and the Python boot (python/).
    From source: var/bridges/dotnet (tools/build_bridges.py) and bridges/python. Inside cig.exe they are bundled, but a
    one-file exe unpacks to a temporary folder that goes away when CIG exits while a launched program still uses its
    bridge - so they are copied once to %LOCALAPPDATA%/CIG/bridges/<version>/ and used from there."""
    import os
    import shutil
    if os.environ.get("CIG_BRIDGES"):
        return Path(os.environ["CIG_BRIDGES"])
    if not config.FROZEN:
        d = config.REPO / "var" / "bridges"
        py = d / "python"
        src = config.REPO / "bridges" / "python"
        if src.is_dir() and not py.exists():
            shutil.copytree(src, py)                    # one layout for both: <assets>/dotnet and <assets>/python
        elif src.is_dir():
            for f in src.glob("*.py"):
                if not (py / f.name).exists() or (py / f.name).read_bytes() != f.read_bytes():
                    shutil.copy2(f, py / f.name)
        return d
    from .. import __version__
    stable = config.home() / "bridges" / __version__
    if not (stable / "dotnet" / "Cig.Bridge.DotNet.dll").is_file() or not (stable / "python").is_dir():
        bundled = config.REPO / "bridge-assets"
        if bundled.is_dir():
            shutil.copytree(bundled, stable, dirs_exist_ok=True)
    return stable


def status() -> dict:
    a = assets_dir()
    return {"assets": str(a), "dotnet": (a / "dotnet" / "Cig.Bridge.DotNet.dll").is_file(),
            "python": (a / "python" / "cig_bridge_boot.py").is_file()}


def register(pid: int, info: dict) -> None:
    if info.get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise AdapterError("refusing a bridge that is not on loopback")
    with _LOCK:
        BRIDGES[int(pid)] = info


def call(info: dict, cmd: str, timeout: float = 20.0, **args) -> dict:
    try:
        with socket.create_connection((info["host"], int(info["port"])), timeout=timeout) as s:
            s.sendall((json.dumps({"token": info["token"], "cmd": cmd, "args": args}) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise AdapterError(f"the bridge did not answer: {e}") from e
    r = json.loads(buf.decode("utf-8") or "{}")
    if not r.get("ok", False):
        raise AdapterError(f"bridge: {r.get('error', 'no answer')}")
    return r


class BridgeAdapter(Adapter):
    name = "bridge"

    def resolve(self, app: str) -> Optional[Target]:
        a = str(app)
        pid = int(a) if a.isdigit() and int(a) in BRIDGES else None
        if pid is None:
            for p in list(BRIDGES):
                try:
                    if psutil.Process(p).name().lower() == a.lower():
                        pid = p
                        break
                except psutil.Error:
                    continue
        if pid is None or not psutil.pid_exists(pid):
            return None
        info = BRIDGES[pid]
        try:
            exe = psutil.Process(pid).name()
        except psutil.Error:
            return None
        return Target(key=f"{exe}|bridge-{info.get('bridge')}|{pid}", exe=exe, pid=pid,
                      title=f"{info.get('bridge')} bridge", adapter=f"bridge:{info.get('bridge')}")

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        r = call(BRIDGES[target.pid], "tree")
        return r.get("windows", [])

    def _live(self, target: Target, locator: str) -> Optional[dict]:
        for node, loc, _p, _w in loc_mod.walk(self.snapshot(target)):
            if loc == locator:
                return node
        return None

    def read(self, target: Target, locator: str, node: dict) -> dict:
        live = self._live(target, locator)
        if live is None:
            return {"exists": False}
        keep = ("name", "value", "toggle_state", "selected", "expand_state", "range", "enabled", "is_read_only")
        return {"exists": True, **{k: live[k] for k in keep if k in live}}

    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        live = self._live(target, locator)
        if live is None or not live.get("bridge"):
            raise AdapterError(f"element gone before acting: {locator}")
        call(BRIDGES[target.pid], "act", path=live["bridge"], action=action, **args)
        return {"detail": f"bridge {action} on {live['bridge']}"}
