"""Start and close programs safely (plan 2.6 item 10, past-mistakes 7623 / 3712).

launch: refused by the safety layer like any write (presence, deny list); always at normal integrity - when CIG itself
        runs elevated the program is started through Explorer, which runs unelevated. Waits for the program's window
        (also when an app-execution alias such as notepad.exe hands over to another process).
close:  graceful only - WM_CLOSE to the program's windows; never TerminateProcess.
"""
from __future__ import annotations

import ctypes
import os
import re
import socket
import subprocess
import time
from typing import Optional

import psutil
import win32con
import win32gui

from . import actionlog, config, guards, presence
import shutil

from .detect import pe_subsystem, windows_of
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


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def appx_target(ref: str) -> Optional[dict]:
    """'appx:<PackageFamilyName>!<AppId>' -> {"aumid", "executable"} read from the installed package's manifest."""
    if not str(ref).startswith("appx:"):
        return None
    aumid = ref[5:]
    fam, _, app_id = aumid.partition("!")
    if not re.fullmatch(r"[A-Za-z0-9._-]+_[a-z0-9]{13}", fam) or not re.fullmatch(r"[A-Za-z0-9._-]+", app_id or ""):
        raise ValueError(f"not a package family!app id: {aumid}")
    ps = (f"$p = Get-AppxPackage | Where-Object PackageFamilyName -eq '{fam}' | Select-Object -First 1; "
          f"if ($p) {{ ([xml](Get-Content (Join-Path $p.InstallLocation 'AppxManifest.xml'))).Package.Applications."
          f"Application | Where-Object Id -eq '{app_id}' | ForEach-Object {{ $_.Executable }} }}")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                       timeout=30, stdin=subprocess.DEVNULL)
    exe = (r.stdout or "").strip().splitlines()
    if not exe:
        raise ValueError(f"package {fam} with app '{app_id}' is not installed")
    return {"aumid": aumid, "executable": os.path.basename(exe[0])}


def isolation_env(exe: str, profile: Optional[str]) -> dict:
    """Environment variables a program's library entry needs so that ALL its data goes to the separate profile
    (library/apps/<app>.json, "isolation": {"env": {...}}; '{profile}' is the CIG profile folder)."""
    if not profile:
        return {}
    from .detect import app_entries
    name = os.path.basename(exe).lower()
    out = {}
    for app in app_entries():
        if name in [x.lower() for x in app.get("exe", [])]:
            iso = app.get("isolation") or {}
            for k, v in (iso.get("env") or {}).items():
                out[k] = str(v).replace("{profile}", profile)
            for d in iso.get("mkdirs") or []:          # folders the redirected paths must already have
                os.makedirs(str(d).replace("{profile}", profile), exist_ok=True)
    return out


def profile_dir(exe: str) -> str:
    d = config.home() / "profiles" / (os.path.splitext(os.path.basename(exe))[0].lower() + "-cig")
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def launch(exe: str, args: list[str], policy: Optional[Policy] = None, confirm: Optional[str] = None,
           wait_s: float = 25.0, cdp: bool = False, profile_flag: Optional[str] = None,
           bridge: Optional[str] = None) -> dict:
    """cdp=True: start with a debugging port on 127.0.0.1 and a separate data folder (profile_flag names the
    program's own option for it, e.g. Vortex '--user-data', Chromium '--user-data-dir='). Without a separate data
    folder a CDP launch is refused: CIG never drives a program over CDP inside someone's real profile (plan 2.6)."""
    policy = policy or Policy.load()
    name = os.path.basename(exe)
    args = list(args or [])
    pres = presence.read()
    dec = decide(Request(app=name, action="launch", kind=WRITE, confirm=confirm), pres, policy)
    entry = {"app": name, "action": "launch", "kind": WRITE, "args": args, "presence": pres.as_dict(),
             "policy": dec.as_dict(), "confirm": confirm, "cdp": cdp}
    if dec.allowed and cdp:
        if not profile_flag:
            dec.allowed, dec.reason = False, ("a CDP launch needs profile_flag (the program's own option for a "
                                              "separate data folder) - CIG never uses a real profile over CDP")
        elif _elevated():
            dec.allowed, dec.reason = False, "CIG runs elevated and cannot pass a CDP launch's arguments unelevated"
    if not dec.allowed:
        entry.update(ok=False, refused=True, reason=dec.reason)
        return {**entry, "log_id": actionlog.write(entry)}
    port = None
    if cdp:
        port = _free_port()
        prof = profile_dir(exe)
        args += [f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1"]
        args += [profile_flag + prof] if profile_flag.endswith("=") else [profile_flag, prof]
        entry.update(args=args, profile=prof, port=port)
    # the library's isolation for this program (a separate profile is only real if every path moves with it)
    env = None
    iso = isolation_env(exe, entry.get("profile")) if cdp else {}
    if iso:
        env = {**os.environ, **iso}
        entry["isolation_env"] = sorted(iso)
    # an in-process bridge, loaded by the platform's own documented start-up mechanism (never injected later)
    channel = None
    if bridge:
        from .adapters import bridge as bridge_mod
        benv, channel = bridge_env(bridge, exe, args)
        if benv is None:
            entry.update(ok=False, refused=True, reason=channel)
            return {**entry, "log_id": actionlog.write(entry)}
        if bridge == "python":
            exe, args = benv.pop("__exe__"), benv.pop("__args__")
            name = os.path.basename(exe)
        env = {**(env or os.environ), **benv}
        entry["bridge"] = bridge
    # system side effects the library knows this program causes (e.g. Vortex takes over nxm://): export them first
    tag = f"pending-{os.path.splitext(name)[0].lower()}-{int(time.time() * 1000)}"
    try:
        guard = guards.take(exe, tag)
    except RuntimeError as e:
        entry.update(ok=False, refused=True, reason=f"cannot guard the program's known system side effects: {e}")
        return {**entry, "log_id": actionlog.write(entry)}
    if guard:
        entry["guarded"] = [k["key"] for k in guard["keys"]]
    appx = appx_target(exe)
    if appx:
        name = appx["executable"]                    # the window to wait for belongs to the package's own exe
    before = _windowed_pids(name)
    t0 = time.time()
    try:
        if appx:
            # a packaged (MSIX / Store) app is started by activation, never by running its exe from WindowsApps
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appx['aumid']}"], close_fds=True)
            entry["via"] = f"activation of {appx['aumid']}"
        elif _elevated():
            subprocess.Popen(["explorer.exe", exe], close_fds=True)        # Explorer starts it unelevated
            entry["via"] = "explorer (CIG is elevated)"
        else:
            # a console program started DETACHED has no console at all and some (PowerShell) exit at once
            # (found in M6, 2026-11-20): give console programs a hidden console instead
            path = exe if os.path.isfile(exe) else (shutil.which(exe) or exe)
            console = pe_subsystem(path) == "console"
            flags = (subprocess.CREATE_NO_WINDOW if console else subprocess.DETACHED_PROCESS) \
                | subprocess.CREATE_NEW_PROCESS_GROUP
            # a program starts in its OWN folder, never CIG's: Wabbajack's launcher unpacked a 336 MB update into
            # CIG's repo and Outfit Studio could not find its own files (Tooling agent's survey, 2026-11-20)
            cwd = os.path.dirname(os.path.abspath(path)) if os.path.isfile(path) else None
            subprocess.Popen([exe, *args], close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=cwd)
            entry["via"] = "direct (CIG is not elevated)"
            entry["cwd"] = cwd
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
        if guard:
            entry["guard_restore"] = guards.restore(tag)
    else:
        if guard:
            guards.rename(tag, f"pid-{pid}")
        h = windows_of(pid)
        entry.update(ok=True, refused=False, pid=pid, title=win32gui.GetWindowText(h[0]) if h else "",
                     waited_s=round(time.time() - t0, 1))
        if port:
            from .adapters import cdp as cdp_mod
            t1 = time.time()
            while time.time() - t1 < 20:
                try:
                    if cdp_mod.pages(port):
                        break
                except Exception:                              # noqa: BLE001 - not listening yet
                    pass
                time.sleep(0.5)
            else:
                entry.update(ok=False, reason=f"the program started but no debugger answered on 127.0.0.1:{port} "
                                              f"(it may strip the flag; fall back to UIA)")
            cdp_mod.register(pid, port)
        if channel:
            from .adapters import bridge as bridge_mod
            t2 = time.time()
            while time.time() - t2 < 20 and not os.path.exists(channel):
                time.sleep(0.25)
            if os.path.exists(channel):
                import json as _json
                info = _json.loads(open(channel, encoding="utf-8").read())
                bridge_mod.register(pid, info)
                entry["bridge_ready"] = True
                if int(info.get("pid", pid)) != pid:          # a launcher stub started the real program
                    bridge_mod.register(int(info["pid"]), info)
                    entry["bridge_pid"] = int(info["pid"])
            else:
                err = channel + ".error"
                entry.update(bridge_ready=False, bridge_note=(open(err, encoding="utf-8").read()[:300]
                             if os.path.exists(err) else "the program did not load the bridge (for .NET: Native "
                             "AOT, or startup hooks disabled); CIG falls back to UIA"))
    return {**entry, "log_id": actionlog.write(entry)}


def bridge_env(kind: str, exe: str, args: list) -> tuple:
    """(environment for the launch, channel file) - or (None, reason) when this bridge cannot be used."""
    import uuid
    from .adapters.bridge import bridge_dir
    d = bridge_dir()
    d.mkdir(parents=True, exist_ok=True)
    channel = str(d / f"channel-{uuid.uuid4().hex}.json")
    if kind == "dotnet":
        dll = d / "dotnet" / "Cig.Bridge.DotNet.dll"
        if not dll.is_file():
            return None, f"the .NET bridge is not built ({dll}); run tools/build_bridges.py"
        return {"DOTNET_STARTUP_HOOKS": str(dll), "CIG_BRIDGE_CHANNEL": channel}, channel
    if kind == "python":
        boot = config.REPO / "bridges" / "python" / "cig_bridge_boot.py"
        if not boot.is_file():
            return None, "the Python bridge is missing (bridges/python)"
        # the program is a Python script: start the same interpreter with the bridge first, then the script itself
        return {"CIG_BRIDGE_CHANNEL": channel, "__exe__": exe, "__args__": [str(boot), *args]}, channel
    return None, f"unknown bridge '{kind}' (dotnet, python)"


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
    if not gone:
        # some programs ignore a posted WM_CLOSE (Equalizer APO's Qt Editor, 2026-11-20); UIA's WindowPattern.Close
        # is the same graceful request, made the way the program's own close button makes it
        try:
            from . import uiawalk
            import uiautomation as auto

            def _close_all():
                for h in windows_of(pid):
                    try:
                        uiawalk.pattern(auto.ControlFromHandle(h), "Window").Close()
                    except Exception:                      # noqa: BLE001
                        pass
            uiawalk.run(_close_all, timeout=15)
        except Exception:                                  # noqa: BLE001
            pass
        t1 = time.time()
        while time.time() - t1 < wait_s and psutil.pid_exists(pid):
            time.sleep(0.3)
        gone = not psutil.pid_exists(pid)
    res = {"ok": gone, "pid": pid, "closed": gone}
    if not gone:
        res["still_open"] = [win32gui.GetWindowText(h) for h in windows_of(pid)]
        res["hint"] = ("the program is asking something before it closes: call cig_actions and answer the window "
                       "with its answer_dialog action")
    else:
        time.sleep(1.0)                                    # let its child processes finish their own writes
        g = guards.restore(f"pid-{pid}")
        if g.get("guard"):
            res["side_effects_restored"] = g
            res["ok"] = bool(g.get("all_restored"))
    actionlog.write({"action": "close_app", "kind": WRITE, "pid": pid, **res})
    return res
