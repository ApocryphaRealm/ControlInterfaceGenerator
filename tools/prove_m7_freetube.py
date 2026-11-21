"""M7 proof (plan 4.4), CDP half: FreeTube - an installed Electron program CIG has never been given code for - driven
over CDP through CIG's MCP server, on a proven-isolated profile (tools/prove_isolation.py), with only library entries
and rules. The script knows nothing about FreeTube's settings: it opens 'Settings', takes the first switch CIG offers
whose label has no destructive word, toggles it and back with read-backs, and types into the search box without
submitting it (no network request). Independent checks: the owner's FreeTube folder byte-identical to its backup
manifest, and the freetube:// handler identical to the script's own snapshot.

  py -3 tools/prove_m7_freetube.py <manifest.json>     writes docs/proofs/M7-freetube.md; exit 0 when all passed
"""
import asyncio
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import folder_snapshot  # noqa: E402
from cig.classify import destructive_hits  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

EXE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeTube\FreeTube.exe")
REAL = os.path.expandvars(r"%APPDATA%\FreeTube")
KEY = r"HKCU\Software\Classes\freetube"
steps: list[dict] = []


class StopProof(Exception):
    pass


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:260])
    if not ok:
        raise StopProof(name)


def reg_lines():
    f = REPO / "var" / "proof" / "freetube-key.reg"
    f.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["reg", "export", KEY, str(f), "/y"], capture_output=True)
    return sorted(x for x in f.read_bytes().decode("utf-16").splitlines() if x.strip())


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


async def _run(s):
    la = await call(s, "cig_launch", exe=EXE, cdp=True, profile_flag="--user-data-dir=")
    step("cig_launch FreeTube with cdp on CIG's own profile", la.get("ok") and "ControlInterfaceGenerator"
         in str(la.get("profile")), {k: la.get(k) for k in ("pid", "port", "profile", "guarded", "reason")})
    app = str(la["pid"])
    det = await call(s, "cig_detect", target=app)
    step("cig_detect: Electron, CDP first", det.get("framework") == "electron" and det["adapters"][0]["name"] == "cdp",
         {"framework": det.get("framework"), "version": det.get("framework_version")})
    settings = None
    for _ in range(30):
        acts = (await call(s, "cig_actions", app=app)).get("actions", [])
        settings = next((a for a in acts if a["action"] == "invoke" and a["label"].endswith("'Settings'")), None)
        if settings:
            break
        await asyncio.sleep(1)
    step("'Settings' is offered over CDP", settings, settings and settings["label"])
    r = await call(s, "cig_do", app=app, action_id=settings["id"])
    step("invoke Settings", r.get("ok"), {k: r.get(k) for k in ("reason", "detail")})
    sw = None
    for _ in range(15):
        acts = (await call(s, "cig_actions", app=app)).get("actions", [])
        cands = [a for a in acts if a["action"] == "set_checked" and not destructive_hits([a["label"]])]
        if cands:
            sw = cands[0]
            break
        await asyncio.sleep(0.7)
    step("a switch is offered on the settings page (first one with no destructive word)", sw, sw and sw["label"])
    before = (await call(s, "cig_read", app=app, element_id=sw["element"])).get("state", {})
    start = before.get("toggle_state")
    step("read the switch's state", start in ("On", "Off"), before)
    want = start != "On"
    r1 = await call(s, "cig_do", app=app, action_id=sw["id"], args={"checked": want})
    step(f"set_checked {want}, verified by read-back", r1.get("ok") and r1.get("verified"),
         {k: r1.get(k) for k in ("reason", "verified")})
    r2 = await call(s, "cig_do", app=app, action_id=sw["id"], args={"checked": not want})
    step(f"set_checked back to {not want}, verified", r2.get("ok") and r2.get("verified"),
         {k: r2.get(k) for k in ("reason", "verified")})
    acts = (await call(s, "cig_actions", app=app)).get("actions", [])
    box = next((a for a in acts if a["action"] == "set_text" and "search" in a["label"].lower()), None)
    step("the search box is offered as set_text", box, box and box["label"])
    text = "CIG M7 proof"
    r3 = await call(s, "cig_do", app=app, action_id=box["id"], args={"text": text})
    step("set_text in the search box (not submitted), verified by read-back", r3.get("ok") and r3.get("verified"),
         {k: r3.get(k) for k in ("reason", "verified")})
    cl = await call(s, "cig_close", app=app)
    step("cig_close (graceful); the freetube:// guard restored", cl.get("ok"),
         {"closed": cl.get("closed"), "restored": (cl.get("side_effects_restored") or {}).get("all_restored")})


async def run(manifest):
    want = json.loads(Path(manifest).read_text(encoding="utf-8"))["files"]
    key_before = reg_lines()
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _run(s)
    except StopProof:
        pass
    finally:
        time.sleep(3)
        try:
            changes = folder_snapshot.diff(want, folder_snapshot.manifest(Path(REAL)))
            step("INDEPENDENT: the owner's FreeTube folder is byte-identical to its backup manifest", not changes,
                 changes[:10] or f"{len(want)} files unchanged")
            step("INDEPENDENT: freetube:// handler identical to the script's own snapshot", reg_lines() == key_before,
                 None)
        except StopProof:
            pass


def write():
    out = REPO / "docs" / "proofs" / "M7-freetube.md"
    ok = all(x["ok"] for x in steps) and len(steps) >= 13
    lines = [f"# M7 proof - FreeTube (Electron), never scripted, driven over CDP through CIG ({datetime.datetime.now():%Y-%m-%d %H:%M})",
             "", f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m7_freetube.py`. FreeTube ran on CIG's own profile (`--user-data-dir=`, isolation",
             "proven first by `tools/prove_isolation.py`); the owner's FreeTube folder was backed up and is compared",
             "byte for byte at the end. CIG has no FreeTube code - only `library/apps/freetube.json` (the profile flag and",
             "the freetube:// guard) and the shared rules.", "", "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|")[:200]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run(sys.argv[1]), 400))
    sys.exit(0 if write() else 1)
