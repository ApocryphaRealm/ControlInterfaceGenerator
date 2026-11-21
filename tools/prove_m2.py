"""M2 proof: drive a program CIG has no code for, through the real MCP server over stdio, using only the meta tools.

Default target: Windows 11 Notepad (WinUI 3). The script plays the agent: it reads cig_actions and picks actions by
the labels CIG generated - the menu bar's 'menu' action, the dialog's 'File name' edit, the dialog's 'Open' button,
the document's 'set_text'. CIG itself contains no Notepad code; only library entries and rules.

  py -3 tools/prove_m2.py            writes docs/proofs/M2-<app>.md and exits 0 when every step passed
"""
import asyncio
import datetime
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

PROOF_FILE = REPO / "var" / "proof" / "m2-proof.txt"
ORIGINAL = ""   # empty on purpose: writing into it is a plain write; replacing text would be an overwrite


class StopProof(Exception):
    pass
NEW_TEXT = "CIG M2 proof - this text was set through UI Automation by CIG at {t}, then saved through the File menu."

steps: list[dict] = []


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:300])
    if not ok:
        # STOP at the first failure (2026-11-20: after a failed open, the script wrote into a restored session tab
        # that held one of the owner's documents). Nothing after a failed step is safe to do.
        raise StopProof(name)
    return ok


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


def pick(actions, action, label_has=None, ctype=None):
    for a in actions:
        if a["action"] != action:
            continue
        if label_has and label_has.lower() not in a["label"].lower():
            continue
        if ctype and f" {ctype} " not in a["label"]:
            continue
        return a
    return None


async def run():
    try:
        return await _run()
    except StopProof:
        return None


async def _run():
    PROOF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROOF_FILE.write_text(ORIGINAL, encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            st = await call(s, "cig_status")
            step("server up, presence read", st.get("ok"), {"adapters": st.get("adapters"), "presence": st.get("presence")})

            la = await call(s, "cig_launch", exe="notepad.exe")
            if not step("cig_launch notepad.exe", la.get("ok"), {k: la.get(k) for k in ("pid", "title", "reason", "via")}):
                return
            app = str(la["pid"])
            await asyncio.sleep(1.5)

            det = await call(s, "cig_detect", target=app)
            step("cig_detect", det.get("framework") == "winui3",
                 {"framework": det.get("framework"), "version": det.get("framework_version"),
                  "adapters": det.get("adapters")})

            acts = (await call(s, "cig_actions", app=app))["actions"]
            menu = pick(acts, "menu")
            if not step("a generated 'menu' action exists", menu, {"menu": menu and menu["label"],
                                                                     "examples": menu and menu["input_schema"]["properties"]["path"].get("examples")}):
                return
            r1 = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/Open"})
            if not step("menu File/Open", r1.get("ok"), {k: r1.get(k) for k in ("reason", "detail", "status")}):
                return

            wt = await call(s, "cig_wait", app=app, title_contains="Open", timeout_s=15)
            step("the Open dialog appeared", wt.get("ok"), wt)
            acts = (await call(s, "cig_actions", app=app))["actions"]
            fname = pick(acts, "set_text", "File name")
            if not step("the dialog's 'File name' edit is offered as set_text", fname, fname and fname["label"]):
                return
            r2 = await call(s, "cig_do", app=app, action_id=fname["id"], args={"text": str(PROOF_FILE)})
            step("set_text file name (read back)", r2.get("ok") and r2.get("verified"), {k: r2.get(k) for k in ("reason", "verified")})

            dlg = next((a for a in acts if a["action"] == "answer_dialog"
                        and "Open" in (a["input_schema"]["properties"]["button"].get("enum") or [])), None)
            if not step("the dialog is offered as answer_dialog with an 'Open' button", dlg,
                        dlg and dlg["input_schema"]["properties"]["button"]["enum"]):
                return
            r3 = await call(s, "cig_do", app=app, action_id=dlg["id"], args={"button": "Open"})
            step("answer_dialog Open", r3.get("ok"), {k: r3.get(k) for k in ("reason", "verified", "detail")})
            gone = await call(s, "cig_wait", app=app, element_id=dlg["element"], state="gone", timeout_s=15)
            step("the dialog closed", gone.get("ok"), gone)
            await asyncio.sleep(1.0)

            acts = (await call(s, "cig_actions", app=app))["actions"]
            doc_set = pick(acts, "set_text", ctype="Document") or pick(acts, "set_text", ctype="Edit")
            doc_get = pick(acts, "get_text", ctype="Document") or pick(acts, "get_text", ctype="Edit")
            if not step("the document is offered as set_text", doc_set, doc_set and doc_set["label"]):
                return
            tree = await call(s, "cig_tree", app=app, depth=1)
            title = tree.get("target", {}).get("title", "")
            step("GUARD: the active window/tab is the proof file (title names it)", PROOF_FILE.name.lower() in title.lower()
                 or PROOF_FILE.stem.lower() in title.lower(), title)
            before = await call(s, "cig_read", app=app, element_id=doc_set["element"])
            step("GUARD: the opened document is the empty proof file", str(before.get("state", {}).get("value", "")).strip()
                 == ORIGINAL, before.get("state", {}).get("value", "")[:120])

            new_text = NEW_TEXT.format(t=datetime.datetime.now().strftime("%H:%M:%S"))
            r4 = await call(s, "cig_do", app=app, action_id=doc_set["id"], args={"text": new_text})
            step("set_text on the document, verified by read-back", r4.get("ok") and r4.get("verified"),
                 {"reason": r4.get("reason"), "after": (r4.get("changed") or {}).get("after", {}).get("value", "")[:120]})
            rd = await call(s, "cig_read", app=app, element_id=doc_set["element"])
            step("cig_read returns the new text", rd.get("state", {}).get("value", "").strip() == new_text,
                 rd.get("state", {}).get("value", "")[:120])

            acts = (await call(s, "cig_actions", app=app))["actions"]
            menu = pick(acts, "menu")
            r5 = await call(s, "cig_do", app=app, action_id=menu["id"], args={"path": "File/Save"})
            step("menu File/Save", r5.get("ok"), {k: r5.get(k) for k in ("reason", "detail")})
            await asyncio.sleep(1.5)
            disk = PROOF_FILE.read_text(encoding="utf-8-sig")
            step("the file on disk holds the new text", disk.strip() == new_text, disk[:120])

            acts = (await call(s, "cig_actions", app=app))["actions"]
            close = pick(acts, "close_window")
            r6 = await call(s, "cig_do", app=app, action_id=close["id"]) if close else {"ok": False}
            step("close_window (graceful)", r6.get("ok"), {k: r6.get(k) for k in ("reason", "verified")})
            log = await call(s, "cig_log", n=40)
            return log.get("entries", [])


def write(log):
    out = REPO / "docs" / "proofs" / "M2-notepad.md"
    ok = all(x["ok"] for x in steps) and len(steps) >= 15
    lines = [f"# M2 proof - Notepad driven through CIG's MCP server ({datetime.datetime.now():%Y-%m-%d %H:%M})", "",
             f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m2.py`, which talks MCP over stdio to `cig_server.py` and picks actions by the",
             "labels CIG generated. CIG has no Notepad code: the menu, the file dialog, the document and the save all",
             "come from `library/rules/uia.json` and the UIA adapter.", "",
             "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|")[:220]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    lines += ["", "## Action log entries for the run (from `cig_log`)", "", "```"]
    for e in log or []:
        lines.append(json.dumps({k: e.get(k) for k in ("time", "app", "action", "action_id", "kind", "ok", "refused",
                                                        "reason", "resolved", "element")}, ensure_ascii=False)[:400])
    lines.append("```")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


if __name__ == "__main__":
    log = asyncio.run(asyncio.wait_for(run(), 300))
    sys.exit(0 if write(log) else 1)
