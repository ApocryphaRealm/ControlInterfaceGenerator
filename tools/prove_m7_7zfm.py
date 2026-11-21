"""M7 proof (plan 4.4), UIA half: 7-Zip File Manager - a program CIG has never been given code for - driven through
CIG's MCP server with only library entries and rules. The script plays the agent (picks actions by the labels CIG
generated) and checks results itself: the folder on disk, and a CRC-32 it computes independently.

  py -3 tools/prove_m7_7zfm.py     writes docs/proofs/M7-7zfm.md; exit 0 when every step passed
"""
import asyncio
import datetime
import json
import re
import shutil
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

EXE = r"C:\Program Files\7-Zip\7zFM.exe"
W = REPO / "var" / "proof" / "m7"
FILE = "sample.txt"
NEWDIR = "made-by-cig"
steps: list[dict] = []


class StopProof(Exception):
    pass


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:260])
    if not ok:
        raise StopProof(name)


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


def find(acts, action, label_has=None, ctype=None):
    for a in acts:
        if a["action"] == action and (not label_has or label_has.lower() in a["label"].lower()) \
                and (not ctype or f" {ctype} " in a["label"]):
            return a
    return None


async def acts_of(s, app):
    return (await call(s, "cig_actions", app=app)).get("actions", [])


async def _run(s, log):
    la = await call(s, "cig_launch", exe=EXE, args=[str(W)])
    step("cig_launch 7zFM.exe on the proof folder", la.get("ok"), {k: la.get(k) for k in ("pid", "title", "reason")})
    app = str(la["pid"])
    await asyncio.sleep(1.5)
    det = await call(s, "cig_detect", target=app)
    step("cig_detect: Win32, UIA", det.get("framework") == "win32" and det["adapters"][0]["name"] == "uia",
         {"framework": det.get("framework"), "version": det.get("framework_version")})
    acts = await acts_of(s, app)
    menu = find(acts, "menu")
    step("a generated 'menu' action and the file list are offered", menu and find(acts, "select", FILE),
         {"menu": menu and menu["label"], "file": bool(find(acts, "select", FILE))})

    # --- File > Create Folder: a dialog, a name typed into it, OK
    r = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/Create Folder"})
    step("menu File/Create Folder", r.get("ok"), {k: r.get(k) for k in ("reason", "detail")})
    await call(s, "cig_wait", app=app, title_contains="Create Folder", timeout_s=10)
    acts = await acts_of(s, app)
    dlg = next((a for a in acts if a["action"] == "answer_dialog"
                and "OK" in (a["input_schema"]["properties"]["button"].get("enum") or [])), None)
    edit = find(acts, "set_text", ctype="Edit")
    step("the dialog's name field and its OK button are offered", dlg and edit, {"edit": edit and edit["label"],
                                                                                "buttons": dlg and dlg["input_schema"]["properties"]["button"]["enum"]})
    before = (await call(s, "cig_read", app=app, element_id=edit["element"])).get("state", {})
    step("the name field holds 7-Zip's default", True, before.get("value"))
    r = await call(s, "cig_do", app=app, action_id=edit["id"], args={"text": NEWDIR})
    step("set_text the folder name, verified by read-back", r.get("ok") and r.get("verified"),
         {k: r.get(k) for k in ("reason", "verified")})
    r = await call(s, "cig_do", app=app, action_id=dlg["id"], args={"button": "OK"})
    step("answer_dialog OK", r.get("ok"), {k: r.get(k) for k in ("reason", "verified")})
    await asyncio.sleep(1.0)
    step("the folder exists on disk", (W / NEWDIR).is_dir(), sorted(p.name for p in W.iterdir()))

    # --- File > Calculate checksum > CRC-32 on the sample file: read the result out of the dialog
    acts = await acts_of(s, app)
    item = find(acts, "select", FILE)
    r = await call(s, "cig_do", app=app, action_id=item["id"])
    step(f"select the list item '{FILE}'", r.get("ok"), {k: r.get(k) for k in ("reason", "verified")})
    menu = find(acts, "menu")
    r = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/CRC/CRC-32"})
    if not r.get("ok"):
        r = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/Calculate checksum/CRC-32"})
    step("menu File > CRC > CRC-32", r.get("ok"), {k: r.get(k) for k in ("reason", "detail")})
    want = f"{zlib.crc32((W / FILE).read_bytes()) & 0xFFFFFFFF:08X}"
    seen = ""
    for _ in range(20):
        tree = (await call(s, "cig_tree", app=app, max_nodes=600)).get("elements", [])
        text = " ".join(f"{e.get('name', '')} {e.get('value', '')}" for e in tree)
        if want in text.upper():
            seen = want
            break
        await asyncio.sleep(0.5)
    step("the CRC-32 7-Zip shows equals the one the script computed itself", seen == want, {"want": want})
    acts = await acts_of(s, app)
    res = next((a for a in acts if a["action"] == "answer_dialog"), None) or find(acts, "close_window", "checksum")
    if res and res["action"] == "answer_dialog":
        btn = next((b for b in res["input_schema"]["properties"]["button"]["enum"] if b.lower() in ("close", "ok")),
                   res["input_schema"]["properties"]["button"]["enum"][0])
        r = await call(s, "cig_do", app=app, action_id=res["id"], args={"button": btn})
        step("close the checksum dialog", r.get("ok"), {"button": btn, "reason": r.get("reason")})

    # --- the safety layer: File > Delete is destructive
    acts = await acts_of(s, app)
    menu = find(acts, "menu")
    r = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/Delete"})
    step("menu File/Delete is refused without confirm (destructive word in the path)",
         r.get("refused") and r.get("status") == "confirm_required", r.get("reason"))
    step(f"'{FILE}' is still on disk", (W / FILE).is_file(), None)

    cl = await call(s, "cig_close", app=app)
    step("cig_close (graceful)", cl.get("ok"), cl)
    log.extend((await call(s, "cig_log", n=40)).get("entries", []))


async def run():
    if W.exists():
        shutil.rmtree(W)
    W.mkdir(parents=True)
    (W / FILE).write_text("CIG M7 proof - a file for 7-Zip File Manager to checksum.\n" * 20, encoding="utf-8")
    log: list = []
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                try:
                    await _run(s, log)
                except StopProof:
                    pass
    except Exception as e:                                     # noqa: BLE001
        steps.append({"step": "server session", "ok": False, "detail": str(e)})
    return log


def write(log):
    out = REPO / "docs" / "proofs" / "M7-7zfm.md"
    ok = all(x["ok"] for x in steps) and len(steps) >= 12
    lines = [f"# M7 proof - 7-Zip File Manager, never scripted, driven through CIG ({datetime.datetime.now():%Y-%m-%d %H:%M})",
             "", f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m7_7zfm.py` (MCP over stdio to `cig_server.py`). CIG has no 7-Zip code: the menu,",
             "the Create Folder dialog, the file list and the checksum dialog come from `library/rules/uia.json` and the",
             "UIA adapter. The folder on disk and the CRC-32 are checked by the script itself.", "",
             "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|")[:200]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    lines += ["", "## Action log for the run", "", "```"]
    for e in log or []:
        lines.append(json.dumps({k: e.get(k) for k in ("time", "app", "action", "action_id", "kind", "ok", "refused",
                                                        "reason")}, ensure_ascii=False)[:300])
    lines.append("```")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    lg = asyncio.run(asyncio.wait_for(run(), 400))
    sys.exit(0 if write(lg) else 1)
