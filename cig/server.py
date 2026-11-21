r"""CIG MCP server (stdio) - the fixed meta tools (plan 2.5). The safety layer is enforced inside the engine; the tool
annotations are hints for the client only.

Register (user scope):
  claude mcp add --scope user cig -- py -3 "D:\Claude output\6. current wip mods\ControlInterfaceGenerator\cig_server.py"
"""
from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import __version__, actionlog, backups, presence
from .adapters.base import AdapterError
from .engine import Engine

mcp = FastMCP("cig")
_ENGINE: Optional[Engine] = None

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RW = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def default_adapters() -> list:
    out = []
    if os.environ.get("CIG_FIXTURES") or os.environ.get("CIG_ENABLE_FIXTURES") == "1":
        from .adapters.fixture import FixtureAdapter
        out.append(FixtureAdapter())
    try:
        from .adapters.host_mo2 import HostMo2Adapter  # M3: claims only 'mo2' / 'host:mo2...' / 'mo2:<instance>'
        out.append(HostMo2Adapter())
    except ImportError:
        pass
    try:
        from .adapters.cdp import CdpAdapter         # M4: before UIA - only programs CIG launched with cdp=true
        out.append(CdpAdapter())
    except ImportError:
        pass
    try:
        from .adapters.uia import UiaAdapter          # M2
        out.append(UiaAdapter())
    except ImportError:
        pass
    return out


def engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = Engine(default_adapters())
    return _ENGINE


def set_engine(e: Engine) -> None:
    global _ENGINE
    _ENGINE = e


def _guard(fn, *a, **kw) -> dict:
    try:
        return fn(*a, **kw)
    except AdapterError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(annotations=RO)
def cig_status() -> dict:
    """CIG version, adapters loaded, the presence reading the safety layer would use now, and the policy thresholds."""
    e = engine()
    return {"ok": True, "version": __version__, "adapters": [a.name for a in e.adapters],
            "presence": presence.read().as_dict(),
            "policy": {"idle_min": e.policy.idle_min, "third_party_foreground_min": e.policy.third_party_foreground_min,
                       "deny_actions": sorted(e.policy.deny_actions)}}


@mcp.tool(annotations=RO)
def cig_apps() -> dict:
    """Programs with windows that CIG can see now (pid, exe, title, detected framework where known)."""
    from .detect import list_apps
    return {"ok": True, "apps": list_apps()}


@mcp.tool(annotations=RO)
def cig_detect(target: str) -> dict:
    """Detect what a program is built with (framework + version + ranked adapters). target = pid, exe name or path."""
    try:
        from .detect import detect                    # M1
    except ImportError:
        return {"ok": False, "error": "the detector arrives in milestone M1"}
    return _guard(detect, target)


@mcp.tool(annotations=RW)
def cig_launch(exe: str, args: Optional[list[str]] = None, cdp: bool = False,
               profile_flag: Optional[str] = None) -> dict:
    """Start a program at normal integrity (never elevated). Refused while the person is using the machine.
    cdp=true (Chromium / Electron): also open a debugging port on 127.0.0.1 and use a SEPARATE data folder inside
    CIG's own space - profile_flag is the program's option for that folder (Vortex '--user-data', Chromium
    '--user-data-dir='). The program is then driven through CDP instead of UIA."""
    from .launch import launch
    r = _guard(launch, exe, args or [], engine().policy, None, 25.0, cdp, profile_flag)
    if r.get("ok") and r.get("pid"):
        engine().register_launch(r["pid"], exe)      # provenance: the only windows CIG may write into
    return r


@mcp.tool(annotations=RW)
def cig_close(app: str) -> dict:
    """Close a program CIG launched, gracefully (WM_CLOSE to its windows; never forced). A save prompt that appears
    is left open and reported - answer it with cig_do."""
    try:
        _a, t = engine().resolve(app)
    except AdapterError as e:
        return {"ok": False, "error": str(e)}
    if t.pid not in engine().launched:
        return {"ok": False, "refused": True, "reason": "CIG closes only programs it launched"}
    from .launch import close
    return close(t.pid)


@mcp.tool(annotations=RO)
def cig_tree(app: str, depth: int = 12, max_nodes: int = 400) -> dict:
    """The app's element tree, compact, each element with a short stable id. app = pid, exe name or window title."""
    return _guard(engine().tree, app, depth, max_nodes)


@mcp.tool(annotations=RO)
def cig_actions(app: str, depth: int = 12) -> dict:
    """The generated typed action set for the app: id '<element>.<action>', kind, label, JSON input schema."""
    return _guard(engine().actions, app, depth)


@mcp.tool(annotations=RW)
def cig_do(app: str, action_id: str, args: Optional[dict[str, Any]] = None, dry_run: bool = False,
           confirm: Optional[str] = None) -> dict:
    """Perform one action from cig_actions. Writes are refused while the person is using the machine unless `confirm`
    carries the person's own words; destructive actions always need `confirm`; deny-listed actions never run.
    `dry_run` resolves and checks everything and returns a preview without acting."""
    return _guard(engine().do, app, action_id, args or {}, dry_run, confirm)


@mcp.tool(annotations=RO)
def cig_read(app: str, element_id: str) -> dict:
    """Read one element's current state (value, toggle, selection) freshly from the program."""
    return _guard(engine().read, app, element_id)


@mcp.tool(annotations=RO)
def cig_wait(app: str, element_id: Optional[str] = None, state: str = "exists",
             title_contains: Optional[str] = None, timeout_s: float = 10.0) -> dict:
    """Wait until an element exists / is gone, or a window whose title contains a text appears."""
    return _guard(engine().wait, app, element_id, state, title_contains, min(float(timeout_s), 120.0))


@mcp.tool(annotations=RO)
def cig_see(app: str) -> Any:
    """One screenshot of the app's own window, on request only (for orientation; CIG never records)."""
    try:
        from .see import see                          # M2
    except ImportError:
        return {"ok": False, "error": "cig_see arrives in milestone M2"}
    return _guard(see, engine(), app)


@mcp.tool(annotations=RO)
def cig_log(n: int = 20) -> dict:
    """The last n entries of CIG's action log (refusals included)."""
    return {"ok": True, "entries": actionlog.tail(n)}


@mcp.tool(annotations=RW)
def cig_undo(backup_id: str) -> dict:
    """Restore the files a backed-up action changed."""
    r = backups.undo(backup_id)
    actionlog.write({"action": "undo", "kind": "write", "backup": backup_id, "ok": r.get("ok"), "result": r})
    return r


def main() -> None:
    mcp.run()
