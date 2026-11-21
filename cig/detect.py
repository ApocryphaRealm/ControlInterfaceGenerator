"""Framework detection (plan 2.2): cheapest probes first, each adding weighted evidence; the result is a ranked list
of frameworks and adapters, not one answer. Read-only: nothing is injected into the target.

  detect(target)   target = pid, exe name ("notepad.exe"), exe path, or a window title fragment
  list_apps()      every process with a visible titled window, with a quick (no UIA) framework guess
"""
from __future__ import annotations

import ctypes
import functools
import json
import os
import re
from pathlib import Path
from typing import Optional

import psutil
import win32api
import win32con
import win32gui
import win32process

from . import config

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
LIST_MODULES_ALL = 0x03
EXE_SCAN_LIMIT = 400 * 1024 * 1024


# ------------------------------------------------------------------------------------------------ library
@functools.lru_cache(maxsize=1)
def library() -> tuple[dict, ...]:
    out = []
    for p in sorted((config.LIBRARY_DIR / "frameworks").glob("*.json")):
        e = json.loads(p.read_text(encoding="utf-8"))
        for key, pats in e["detect"].items():
            for pat in pats:
                pat["_re"] = re.compile(pat["re"], re.I)
        out.append(e)
    return tuple(out)


@functools.lru_cache(maxsize=1)
def app_entries() -> tuple[dict, ...]:
    d = config.LIBRARY_DIR / "apps"
    return tuple(json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))) if d.exists() else ()


# ------------------------------------------------------------------------------------------------ probes
def windows_of(pid: int) -> list[int]:
    """Visible, titled top-level windows of a process, largest first."""
    out = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            if win32process.GetWindowThreadProcessId(h)[1] == pid:
                out.append(h)
        return True
    win32gui.EnumWindows(cb, None)

    def area(h):
        try:
            l, t, r, b = win32gui.GetWindowRect(h)
            return (r - l) * (b - t)
        except win32gui.error:
            return 0
    return sorted(out, key=area, reverse=True)


def window_classes(hwnds: list[int], limit: int = 400) -> list[str]:
    seen: dict[str, None] = {}
    for h in hwnds:
        try:
            seen[win32gui.GetClassName(h)] = None
        except win32gui.error:
            continue
        kids: list[int] = []
        try:
            win32gui.EnumChildWindows(h, lambda c, acc: acc.append(c) or len(acc) < limit, kids)
        except win32gui.error:
            pass
        for c in kids[:limit]:
            try:
                seen[win32gui.GetClassName(c)] = None
            except win32gui.error:
                pass
    return list(seen)


def modules_of(pid: int) -> Optional[list[str]]:
    try:
        h = win32api.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    except win32api.error:
        h = None
    if h:
        try:
            mods = win32process.EnumProcessModulesEx(h, LIST_MODULES_ALL)
            return [win32process.GetModuleFileNameEx(h, m) for m in mods]
        except win32api.error:
            pass
        finally:
            win32api.CloseHandle(h)
    try:
        return [m.path for m in psutil.Process(pid).memory_maps()] or None    # [] = could not read, not "no modules"
    except (psutil.Error, OSError):
        return None


def _version_tuple(v: Optional[str]) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:4])
    except ValueError:
        return ()


def version_ok(v: Optional[str], cond: str) -> bool:
    m = re.fullmatch(r"\s*(>=|<=|>|<|==)\s*([\d.]+)\s*", cond or "")
    if not m:
        return True
    have, want = _version_tuple(v), _version_tuple(m.group(2))
    if not have:
        return False
    have = have[:len(want)]
    return {">=": have >= want, "<=": have <= want, ">": have > want, "<": have < want, "==": have == want}[m.group(1)]


def file_version(path: str) -> dict:
    out = {}
    try:
        fixed = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = fixed["FileVersionMS"], fixed["FileVersionLS"]
        out["file_version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        lang, cp = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
        for key in ("ProductName", "CompanyName", "ProductVersion", "FileDescription"):
            try:
                v = win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}")
                if v:
                    out[key[0].lower() + re.sub(r"(?<!^)([A-Z])", r"_\1", key[1:]).lower()] = str(v).strip()
            except win32api.error:
                pass
    except (win32api.error, TypeError, IndexError, KeyError):
        pass
    return out


def pe_subsystem(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        off = int.from_bytes(head[0x3C:0x40], "little")
        if head[off:off + 4] != b"PE\0\0":
            return None
        sub = int.from_bytes(head[off + 24 + 68: off + 24 + 70], "little")
        return {2: "gui", 3: "console"}.get(sub, f"other:{sub}")
    except OSError:
        return None


def integrity_level(pid: int) -> Optional[str]:
    try:
        import win32security
        h = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            tok = win32security.OpenProcessToken(h, win32con.TOKEN_QUERY)
            sid, _ = win32security.GetTokenInformation(tok, win32security.TokenIntegrityLevel)
            rid = sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)
        finally:
            win32api.CloseHandle(h)
        return ("system" if rid >= 0x4000 else "high" if rid >= 0x3000 else "medium" if rid >= 0x2000
                else "low" if rid >= 0x1000 else "untrusted")
    except Exception:                                      # noqa: BLE001 - protected processes refuse the query
        return None


def scan_exe(path: str, patterns: list[re.Pattern]) -> dict[str, str]:
    """First match of each byte pattern in the exe (chunked; bounded)."""
    found: dict[str, str] = {}
    try:
        size = os.path.getsize(path)
        if size > EXE_SCAN_LIMIT:
            return found
        overlap = b""
        with open(path, "rb") as f:
            while len(found) < len(patterns):
                chunk = f.read(8 * 1024 * 1024)
                if not chunk:
                    break
                buf = overlap + chunk
                for p in patterns:
                    if p.pattern not in found:
                        m = re.search(p.pattern.encode(), buf)
                        if m:
                            found[p.pattern] = m.group(0).decode("ascii", "replace")
                overlap = buf[-256:]
    except OSError:
        pass
    return found


def files_beside(exe: str) -> list[str]:
    base = Path(exe).parent
    out = []
    res = base / "resources"
    if res.is_dir():
        try:
            for p in res.iterdir():
                out.append("resources/" + p.name)
        except OSError:
            pass
        if (res / "app" / "package.json").exists():
            out.append("resources/app/package.json")
    return out


def uia_sample(hwnd: int) -> Optional[dict]:
    try:
        from . import uiawalk
        windows = uiawalk.run(uiawalk.snapshot_hwnds, [hwnd], 5, 300, False, timeout=12)
        r = uiawalk.richness(windows)
        top = windows[0].get("framework_id") if windows else None
        r["top_framework_id"] = top
        return r
    except Exception as e:                                 # noqa: BLE001 - detection reports, it does not fail
        return {"error": str(e)}


# ------------------------------------------------------------------------------------------------ resolution
def resolve_pids(target) -> list[int]:
    t = str(target).strip()
    if t.isdigit():
        return [int(t)] if psutil.pid_exists(int(t)) else []
    name = os.path.basename(t).lower()
    by_name = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if (p.info["name"] or "").lower() == name or (p.info["exe"] or "").lower() == t.lower():
                by_name.append(p.info["pid"])
        except psutil.Error:
            continue
    if by_name:
        windowed = [pid for pid in by_name if windows_of(pid)]
        return windowed or by_name
    # a window title fragment
    hits = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and t.lower() in win32gui.GetWindowText(h).lower():
            hits.append(win32process.GetWindowThreadProcessId(h)[1])
        return True
    win32gui.EnumWindows(cb, None)
    return list(dict.fromkeys(hits))


# ------------------------------------------------------------------------------------------------ scoring
def _score(entry: dict, ev: dict) -> tuple[float, list[str]]:
    score, why = 0.0, []
    sources = {
        "modules": [os.path.basename(m).lower() for m in (ev.get("modules") or [])],
        "window_class": ev.get("window_classes") or [],
        "uia_framework_id": list((ev.get("uia") or {}).get("framework_ids", {}).keys()),
        "files_beside_exe": ev.get("files_beside") or [],
        "exe_strings": list((ev.get("exe_strings") or {}).values()),
        "pe_subsystem": [ev.get("pe_subsystem") or ""],
        "msix": ["msix"] if ev.get("msix") else [],
    }
    for key, pats in entry["detect"].items():
        for pat in pats:
            if key == "modules" and pat.get("version"):
                path = next((m for m in ev.get("modules") or [] if pat["_re"].search(os.path.basename(m))), None)
                if path:
                    v = file_version(path).get("file_version")
                    if version_ok(v, pat["version"]):
                        score += pat["w"]
                        why.append(f"modules: {os.path.basename(path)} {v} ({pat['version']})")
                continue
            hit = next((s for s in sources.get(key, []) if s and pat["_re"].search(s)), None)
            if hit is not None:
                score += pat["w"]
                why.append(f"{key}: {hit}")
    return min(1.0, round(score, 2)), why


def _version(entry: dict, ev: dict) -> Optional[str]:
    vf = entry.get("version_from") or {}
    if "module_re" in vf:
        rx = re.compile(vf["module_re"], re.I)
        for m in ev.get("modules") or []:
            if rx.search(os.path.basename(m)):
                v = file_version(m).get("file_version")
                if v:
                    return v
    if "exe_regex" in vf:
        for s in (ev.get("exe_strings") or {}).values():
            m = re.search(vf["exe_regex"], s)
            if m:
                return m.group(1)
    if vf.get("exe_file_version"):
        return ev.get("version", {}).get("product_version") or ev.get("version", {}).get("file_version")
    return None


def _host_channels(exe: str) -> list[dict]:
    out = []
    for app in app_entries():
        if os.path.basename(exe).lower() not in [x.lower() for x in app.get("exe", [])]:
            continue
        for ch in app.get("host_channels", []):
            f = Path(exe).parent / ch["channel_file"]
            live = False
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                live = (data.get("host") in ("127.0.0.1", "localhost", "::1")
                        and psutil.pid_exists(int(data.get("pid", -1))))
            except (OSError, ValueError, TypeError):
                pass
            out.append({"name": ch["adapter"], "score": ch["base"] if live else 0.0,
                        "note": "channel live" if live else "no live channel.json (plugin not running?)",
                        "app": app["app"]})
    return out


def evidence(pid: int, with_uia: bool = True) -> dict:
    p = psutil.Process(pid)
    try:
        exe = p.exe()
    except psutil.Error:
        exe = ""
    hwnds = windows_of(pid)
    ev = {"pid": pid, "name": p.name(), "exe": exe, "windows": len(hwnds),
          "title": win32gui.GetWindowText(hwnds[0]) if hwnds else "",
          "version": file_version(exe) if exe else {}, "msix": "\\windowsapps\\" in exe.lower(),
          "pe_subsystem": pe_subsystem(exe) if exe else None, "integrity": integrity_level(pid),
          "window_classes": window_classes(hwnds), "modules": modules_of(pid), "files_beside": files_beside(exe) if exe else []}
    try:
        ev["cmdline_has_debug_port"] = any("--remote-debugging-port" in a for a in p.cmdline())
    except psutil.Error:
        ev["cmdline_has_debug_port"] = None
    # the exe's own strings: Electron/Chromium versions, and the marks of frameworks that leave no DLL or window class
    # behind (Delphi's TApplication/Embarcadero, a single-file Avalonia app) - bounded by EXE_SCAN_LIMIT
    if exe:
        pats = [pat["_re"] for e in library() for k, ps in e["detect"].items() if k == "exe_strings" for pat in ps]
        pats += [re.compile(e["version_from"]["exe_regex"]) for e in library() if "exe_regex" in e.get("version_from", {})]
        ev["exe_strings"] = scan_exe(exe, pats)
    if with_uia and hwnds:
        ev["uia"] = uia_sample(hwnds[0])
    return ev


def rank(ev: dict) -> dict:
    scored = []
    for e in library():
        s, why = _score(e, ev)
        if s > 0:
            scored.append((s, e, why))
    # a framework that specializes another wins over it when both match (Electron over Chromium over Win32)
    names = {e["framework"]: (s, e) for s, e, _ in scored}
    suppressed = set()
    for s, e, _ in scored:
        if s >= 0.5:
            suppressed.update(x for x in e.get("specializes", []) if x in names)
    scored.sort(key=lambda x: (x[1]["framework"] not in suppressed, x[0], len(x[1].get("specializes", []))),
                reverse=True)
    ranked = [{"framework": e["framework"], "label": e["label"], "score": s, "generic": e["framework"] in suppressed,
               "evidence": why} for s, e, why in scored]
    top = scored[0][1] if scored else None
    richness = (ev.get("uia") or {}).get("score")
    adapters = []
    if top:
        for a in top["adapters"]:
            sc = a["base"]
            if a["name"] == "uia" and richness is not None:
                sc = round(sc * (0.4 + 0.6 * richness), 2)
            adapters.append({"name": a["name"], "score": sc, **({"needs": a["needs"]} if "needs" in a else {})})
    adapters += _host_channels(ev.get("exe") or "")
    adapters.sort(key=lambda a: a["score"], reverse=True)
    hybrid = [r["framework"] for r in ranked[1:] if not r["generic"] and scored and r["score"] >= scored[0][0] - 0.1]
    return {"framework": top["framework"] if top else "unknown",
            "label": top["label"] if top else "unknown",
            **({"hybrid_with": hybrid} if hybrid else {}),
            "framework_version": _version(top, ev) if top else None,
            "adapter_in_v1": bool(top and top["adapter_in_v1"]),
            "ranked": ranked[:6], "adapters": adapters}


def detect(target, with_uia: bool = True) -> dict:
    pids = resolve_pids(target)
    if not pids:
        p = Path(str(target))
        if p.suffix.lower() == ".exe" and p.exists():         # not running: static evidence only
            ev = {"pid": None, "name": p.name, "exe": str(p), "version": file_version(str(p)),
                  "pe_subsystem": pe_subsystem(str(p)), "files_beside": files_beside(str(p)), "window_classes": [],
                  "msix": "\\windowsapps\\" in str(p).lower()}
            ev["exe_strings"] = scan_exe(str(p), [pat["_re"] for e in library()
                                                  for k, ps in e["detect"].items() if k == "exe_strings" for pat in ps])
            return {"ok": True, "running": False, "process": _summary(ev), **rank(ev)}
        return {"ok": False, "error": f"no running process or exe matches '{target}'"}
    ev = evidence(pids[0], with_uia)
    out = {"ok": True, "running": True, "process": _summary(ev), **rank(ev)}
    if len(pids) > 1:
        out["other_pids"] = pids[1:8]
    return out


def _summary(ev: dict) -> dict:
    uia = ev.get("uia") or {}
    return {"pid": ev.get("pid"), "name": ev.get("name"), "exe": ev.get("exe"), "title": ev.get("title", ""),
            "product": ev.get("version", {}).get("product_name"), "version": ev.get("version", {}).get("product_version")
            or ev.get("version", {}).get("file_version"), "integrity": ev.get("integrity"), "msix": ev.get("msix"),
            "pe_subsystem": ev.get("pe_subsystem"), "window_classes": (ev.get("window_classes") or [])[:12],
            "modules_read": ev.get("modules") is not None, "uia": {k: uia[k] for k in uia if k != "framework_ids"}
            | ({"framework_ids": uia["framework_ids"]} if "framework_ids" in uia else {})}


def list_apps() -> list[dict]:
    seen: dict[int, dict] = {}

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            pid = win32process.GetWindowThreadProcessId(h)[1]
            seen.setdefault(pid, {"pid": pid, "title": win32gui.GetWindowText(h)})
        return True
    win32gui.EnumWindows(cb, None)
    out = []
    for pid, row in seen.items():
        try:
            ev = evidence(pid, with_uia=False)
        except psutil.Error:
            continue
        r = rank(ev)
        out.append({**row, "exe": ev["name"], "framework": r["framework"], "framework_version": r["framework_version"],
                    "integrity": ev.get("integrity")})
    return sorted(out, key=lambda r: r["exe"].lower())
