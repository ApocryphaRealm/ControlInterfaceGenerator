"""M4 proof: an Electron program driven over CDP through CIG's MCP server - Vortex on a TEST data folder only.

The script plays the agent with the meta tools only. Independent of CIG it also checks the two things that must not
change on this machine: the nxm:// handler (CIG's own guard restores it; this script compares against its own
snapshot) and the owner's real Vortex data folder (%APPDATA%/Vortex: newest file time before == after).

  py -3 tools/prove_m4.py      writes docs/proofs/M4-vortex.md; exit 0 when every step passed
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

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

VORTEX = r"C:\Program Files\Vortex\Vortex.exe"
TOGGLE = "Reduce motion"            # UI-only, stored in the test data folder; no system effect
NXM = r"HKCU\Software\Classes\nxm"
steps: list[dict] = []


class StopProof(Exception):
    pass


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:300])
    if not ok:
        raise StopProof(name)


def reg_lines(key):
    out = REPO / "var" / "proof" / "nxm-check.reg"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["reg", "export", key, str(out), "/y"], capture_output=True)
    return sorted(line for line in out.read_bytes().decode("utf-16").splitlines() if line.strip())


def newest_mtime(folder):
    newest = 0.0
    for root, _d, files in os.walk(folder):
        for f in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return newest


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


def pick(actions, action, label_end):
    return next((a for a in actions if a["action"] == action and a["label"].endswith(f"'{label_end}'")), None)


async def _run(s):
    st = await call(s, "cig_status")
    step("server up", st.get("ok"), {"adapters": st.get("adapters"), "presence": st.get("presence")})
    la = await call(s, "cig_launch", exe=VORTEX, cdp=True, profile_flag="--user-data")
    step("cig_launch Vortex with cdp on a test data folder", la.get("ok"),
         {k: la.get(k) for k in ("pid", "port", "profile", "guarded", "reason")})
    step("the test data folder is inside CIG's own space, not the owner's", "ControlInterfaceGenerator" in
         str(la.get("profile")) and "AppData" not in str(la.get("profile")), la.get("profile"))
    app = str(la["pid"])
    det = await call(s, "cig_detect", target=app)
    step("cig_detect: Electron, CDP first", det.get("framework") == "electron" and det["adapters"][0]["name"] == "cdp",
         {"framework": det.get("framework"), "version": det.get("framework_version")})

    settings = None
    for _ in range(40):
        acts = (await call(s, "cig_actions", app=app)).get("actions", [])
        settings = pick(acts, "invoke", "Settings")
        if settings:
            break
        await asyncio.sleep(0.75)
    step("Vortex's 'Settings' button is offered (over CDP)", settings, settings and settings["label"])
    r = await call(s, "cig_do", app=app, action_id=settings["id"])
    step("invoke Settings", r.get("ok"), {k: r.get(k) for k in ("reason", "detail")})

    tg = None
    for _ in range(20):
        acts = (await call(s, "cig_actions", app=app)).get("actions", [])
        tg = pick(acts, "set_checked", TOGGLE)
        if tg:
            break
        await asyncio.sleep(0.5)
    step(f"the custom-drawn '{TOGGLE}' switch is offered as set_checked (widget-kit library)", tg, tg and tg["label"])
    before = (await call(s, "cig_read", app=app, element_id=tg["element"])).get("state", {})
    start = before.get("toggle_state")
    step("read its state", start in ("On", "Off"), before)
    want = start != "On"
    r1 = await call(s, "cig_do", app=app, action_id=tg["id"], args={"checked": want})
    step(f"set_checked {want}, verified by read-back", r1.get("ok") and r1.get("verified"),
         {k: r1.get(k) for k in ("reason", "verified", "changed")})
    rd = (await call(s, "cig_read", app=app, element_id=tg["element"])).get("state", {})
    step("cig_read shows the new state", rd.get("toggle_state") == ("On" if want else "Off"), rd)
    r2 = await call(s, "cig_do", app=app, action_id=tg["id"], args={"checked": not want})
    step(f"set_checked back to {not want}, verified", r2.get("ok") and r2.get("verified"),
         {k: r2.get(k) for k in ("reason", "verified")})

    cl = await call(s, "cig_close", app=app)
    step("cig_close (graceful) and CIG's guard restored the nxm:// handler", cl.get("ok"),
         {"closed": cl.get("closed"), "restored": (cl.get("side_effects_restored") or {}).get("keys")})
    log = await call(s, "cig_log", n=30)
    return log.get("entries", [])


async def run():
    nxm_before = reg_lines(NXM)
    real = os.path.join(os.environ["APPDATA"], "Vortex")
    real_before = newest_mtime(real)
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    log = []
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                log = await _run(s)
    except StopProof:
        pass
    finally:
        time.sleep(2)
        try:
            step("INDEPENDENT: nxm:// handler identical to this script's own snapshot", reg_lines(NXM) == nxm_before,
                 [line for line in reg_lines(NXM) if "command" in line.lower() or "exe" in line.lower()][:2])
            step("INDEPENDENT: the owner's real Vortex data folder was not written",
                 newest_mtime(real) == real_before,
                 {"newest_before": datetime.datetime.fromtimestamp(real_before).isoformat(timespec="seconds")
                  if real_before else None})
        except StopProof:
            pass
    return log


def write(log):
    out = REPO / "docs" / "proofs" / "M4-vortex.md"
    ok = all(x["ok"] for x in steps) and len(steps) >= 15
    lines = [f"# M4 proof - Vortex (Electron) driven over CDP through CIG ({datetime.datetime.now():%Y-%m-%d %H:%M})", "",
             f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m4.py` (MCP over stdio to `cig_server.py`). Vortex ran on a TEST data folder",
             "inside CIG's own `var/profiles`, never the owner's. Its switches are custom-drawn and absent from the",
             "accessibility tree; they are found by the widget-kit library (`library/cdp/dom-widgets.json`), not by",
             "Vortex code.", "", "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|")[:220]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    lines += ["", "## Action log entries for the run", "", "```"]
    for e in log or []:
        lines.append(json.dumps({k: e.get(k) for k in ("time", "app", "action", "action_id", "kind", "ok", "refused",
                                                        "reason")}, ensure_ascii=False)[:300])
    lines.append("```")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    lg = asyncio.run(asyncio.wait_for(run(), 400))
    sys.exit(0 if write(lg) else 1)
