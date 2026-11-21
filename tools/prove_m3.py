"""M3 proof (plan 4.2 exit criterion): a plugin's window and its dialogs inside a running Mod Organizer 2, driven end to
end through CIG's MCP server over stdio - no mouse, no keyboard, no screen control.

The target is MO2 with two of our plugins: MO2 Agent Control 1.1.0 or newer (the channel) and MO2 Modlist Manager
(the window under test). The script plays the agent: it reads cig_actions and picks actions by the labels CIG
generated - the toolbar button, the tab, Apply, each answer of Apply's question, Undo, the Restore picker, Close.
CIG has no Modlist Manager code and no MO2 rule: the host adapter turns the plugin's ui_tree into nodes and the same
library/rules/uia.json that drove Notepad in M2 produces the actions.

  py -3 tools/prove_m3.py --instance "<MO2 instance folder>" [--profile Default]
      writes docs/proofs/M3-mo2-host.md and exits 0 when every step passed.

MO2 must already be running on a SCRATCH instance (this script starts no program), with the profile in a state where
Modlist Manager's Apply asks its "Plugins would be switched off" question. The script compares the profile's three
list files byte for byte after each step and stops at the first failed step, leaving the window as it is.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

FILES = ("modlist.txt", "plugins.txt", "loadorder.txt")
MM = "MO2 Modlist Manager"
QUESTION = "Plugins would be switched off"
steps: list[dict] = []


class StopProof(Exception):
    pass


def step(name, ok, detail):
    steps.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:300], flush=True)
    if not ok:
        raise StopProof(name)          # nothing after a failed step is safe to do
    return ok


async def call(s, tool, **args):
    res = await s.call_tool(tool, args)
    txt = res.content[0].text if res.content else "{}"
    try:
        return json.loads(txt)
    except ValueError:
        return {"ok": False, "raw": txt}


def pick(actions, action, label=None, starts=None, ctype=None):
    hits = []
    for a in actions:
        if a["action"] != action or (ctype and f" {ctype} " not in a["label"]):
            continue
        name = a["label"].split("'", 1)[1].rsplit("'", 1)[0] if "'" in a["label"] else ""
        if (label is not None and name == label) or (starts is not None and name.startswith(starts)):
            hits.append(a)
    return hits[0] if len(hits) == 1 else None


class Profile:
    def __init__(self, instance, profile):
        self.dir = Path(instance) / "profiles" / profile

    def digest(self):
        out = {}
        for f in FILES:
            p = self.dir / f
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None
        return out


async def actions(s, app):
    r = await call(s, "cig_actions", app=app)
    return r.get("actions") or []


async def wait_action(s, app, timeout=90.0, **want):
    """Poll cig_actions until the wanted action is offered (a preview still computing leaves Apply disabled)."""
    t0 = time.time()
    while True:
        a = pick(await actions(s, app), **want)
        if a or time.time() - t0 > timeout:
            return a
        await asyncio.sleep(1.0)


async def status_text(s, app, needle, timeout=15.0):
    """The window's label texts, polled: straight after an Apply the status line is updated a moment later."""
    t0 = time.time()
    while True:
        t = await call(s, "cig_tree", app=app)
        texts = [str(e.get("value", "")) for e in t.get("elements", []) if e.get("type") == "Text"]
        hit = next((x for x in texts if needle.lower() in x.lower()), None)
        if hit or time.time() - t0 > timeout:
            return hit, texts
        await asyncio.sleep(0.7)


async def apply_and_answer(s, app, answer):
    a = await wait_action(s, app, action="invoke", label="Apply", ctype="Button")
    step(f"Apply is offered (before answering '{answer}')", bool(a), a and a["label"])
    r = await call(s, "cig_do", app=app, action_id=a["id"])
    d = r.get("detail") or {}
    step("pressing Apply returns at once with the question described",
         r.get("ok") and d.get("returned") is False and (d.get("modal_open") or {}).get("title") == QUESTION,
         {"returned": d.get("returned"), "modal": (d.get("modal_open") or {}).get("title"),
          "buttons": (d.get("modal_open") or {}).get("buttons"), "cig_backup": r.get("backup"),
          "plugin_backup": d.get("host_backup")})
    acts = await actions(s, app)
    dlg = pick(acts, action="answer_dialog", label=QUESTION)
    enum = (dlg or {}).get("input_schema", {}).get("properties", {}).get("button", {}).get("enum")
    step("the question is a modal Window whose buttons are the answers", bool(dlg) and answer in (enum or []), enum)
    step("nothing behind the question is offered while it is open",
         not pick(acts, action="invoke", label="Close") and not pick(acts, action="invoke", label="Apply", ctype="Button"),
         sorted({x["label"] for x in acts})[:8])
    r = await call(s, "cig_do", app=app, action_id=dlg["id"], args={"button": answer})
    step(f"answer '{answer}': done, and the read-back shows the question gone", r.get("ok") and r.get("verified") is True,
         {"ok": r.get("ok"), "verified": r.get("verified"), "reason": r.get("reason"), "cig_backup": r.get("backup")})
    return r


async def undo(s, app, prof, pre):
    a = await wait_action(s, app, timeout=20.0, action="invoke", label="Undo this Apply")
    step("'Undo this Apply' is offered after the Apply", bool(a), a and a["label"])
    r = await call(s, "cig_do", app=app, action_id=a["id"])
    d = r.get("detail") or {}
    if d.get("returned") is False and d.get("modal_open") and d["modal_open"].get("title") != MM:
        dlg = pick(await actions(s, app), action="answer_dialog", label=d["modal_open"]["title"])
        yes = next((b for b in (dlg or {}).get("input_schema", {}).get("properties", {}).get("button", {}).get("enum", [])
                    if b.replace("&", "").lower() in ("yes", "ok", "undo")), None)
        step("Undo asked a question; answering it", bool(dlg and yes), d["modal_open"])
        r = await call(s, "cig_do", app=app, action_id=dlg["id"], args={"button": yes})
    step("Undo done", r.get("ok"), {"ok": r.get("ok"), "reason": r.get("reason"), "returned": d.get("returned")})
    hit, texts = await status_text(s, app, "undone")
    step("after Undo the three list files are byte-identical to the start", prof.digest() == pre,
         {"status": hit or texts[:2], "files": prof.digest()})


async def run(a):
    app = "mo2:" + a.instance
    prof = Profile(a.instance, a.profile)
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")])
    log = []
    async with stdio_client(params) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            try:
                st = await call(s, "cig_status")
                step("cig_status", st.get("ok", True), {k: st.get(k) for k in ("version", "adapters", "presence") if k in st})
                acts = await actions(s, app)
                btn = pick(acts, action="invoke", label=MM)
                step("MO2's main window: the toolbar button of Modlist Manager is a typed action",
                     bool(btn), {"actions": len(acts), "picked": btn and btn["label"],
                                 "rules_used": sorted({x["rule"] for x in acts})})
                pre = prof.digest()
                step("the profile's list files are there to compare", all(pre.values()), pre)

                r = await call(s, "cig_do", app=app, action_id=btn["id"])
                d = r.get("detail") or {}
                step("open the window: the press returns at once (the window is run modally) with it described",
                     r.get("ok") and d.get("returned") is False and (d.get("modal_open") or {}).get("title") == MM,
                     {"returned": d.get("returned"), "modal": d.get("modal_open"), "cig_backup": r.get("backup")})
                first_backup = r.get("backup")
                step("CIG backed the profile's lists up before the press", bool(first_backup), first_backup)

                tab = pick(await actions(s, app), action="select", starts="Plugins")
                step("the Plugins tab is a typed action", bool(tab), tab and tab["label"])
                r = await call(s, "cig_do", app=app, action_id=tab["id"])
                step("select the Plugins tab, verified by read-back", r.get("ok") and r.get("verified") is True,
                     {"verified": r.get("verified"), "reason": r.get("reason")})

                await apply_and_answer(s, app, "Cancel")
                hit, texts = await status_text(s, app, "cancelled")
                step("after Cancel nothing was written: the three files are byte-identical",
                     prof.digest() == pre, {"status": hit or texts[:2], "files": prof.digest()})

                await apply_and_answer(s, app, "Apply, leave plugins as they are")
                hit, texts = await status_text(s, app, "Applied")
                now = prof.digest()
                step("'leave plugins as they are': modlist.txt re-sorted, plugins.txt and loadorder.txt untouched",
                     now["modlist.txt"] != pre["modlist.txt"] and now["plugins.txt"] == pre["plugins.txt"]
                     and now["loadorder.txt"] == pre["loadorder.txt"], {"status": hit or texts[:2], "before": pre, "after": now})
                await undo(s, app, prof, pre)

                await apply_and_answer(s, app, "Apply and switch them off")
                hit, texts = await status_text(s, app, "Applied")
                now = prof.digest()
                step("'switch them off': plugins.txt changed too", now["plugins.txt"] != pre["plugins.txt"],
                     {"status": hit or texts[:2], "before": pre, "after": now})
                await undo(s, app, prof, pre)

                rb = await wait_action(s, app, timeout=20.0, action="invoke", label="Restore backup...")
                step("'Restore backup...' is offered", bool(rb), rb and rb["label"])
                r = await call(s, "cig_do", app=app, action_id=rb["id"])
                d = r.get("detail") or {}
                title = (d.get("modal_open") or {}).get("title")
                step("Restore opens its own dialog on top", r.get("ok") and d.get("returned") is False and title not in (None, MM),
                     d.get("modal_open"))
                acts = await actions(s, app)
                combo = next((x for x in acts if x["action"] == "choose"), None)
                step("the picker's list of backups is a typed choice", bool(combo),
                     combo and {"label": combo["label"], "options": len(combo["input_schema"]["properties"]["option"].get("enum", []))})
                dlg = pick(acts, action="answer_dialog", label=title)
                r = await call(s, "cig_do", app=app, action_id=dlg["id"], args={"button": "Cancel"})
                step("Cancel the Restore dialog: gone, nothing restored",
                     r.get("ok") and r.get("verified") is True and prof.digest() == pre, {"files": prof.digest()})

                await presence_refusal(a, app)

                close = await wait_action(s, app, timeout=20.0, action="invoke", label="Close")
                r = await call(s, "cig_do", app=app, action_id=close["id"])
                d = r.get("detail") or {}
                step("Close: the press returns and no modal is left", r.get("ok") and d.get("returned") is True
                     and not d.get("modal_open"), {"returned": d.get("returned")})
                back = pick(await actions(s, app), action="invoke", label=MM)
                step("MO2's main window is back and answering", bool(back), back and back["label"])
                step("the profile ends exactly as it started", prof.digest() == pre, prof.digest())
            except StopProof:
                pass
            finally:
                log = (await call(s, "cig_log", n=60)).get("entries") or []
    return log


async def presence_refusal(a, app):
    """A second server whose presence file says the person typed just now: CIG must refuse a write without confirm,
    and with confirm the note must reach the plugin's own log."""
    tmp = Path(tempfile.mkdtemp(prefix="cig-m3-"))
    f = tmp / "owner-real-input.json"
    f.write_text(json.dumps({"last_real_input_epoch": time.time(), "watcher_alive_epoch": time.time()}), encoding="utf-8")
    env = dict(os.environ, CIG_OWNER_REAL_INPUT_FILE=str(f))
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "cig_server.py")], env=env)
    note = f"M3 proof {datetime.datetime.now():%H:%M:%S}: the tester approved this recompute"
    async with stdio_client(params) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            again = await wait_action(s, app, timeout=20.0, action="invoke", label="Compute again")
            step("(person active) 'Compute again' is offered", bool(again), again and again["label"])
            r = await call(s, "cig_do", app=app, action_id=again["id"])
            step("(person active) the write is REFUSED without confirm, before anything reaches MO2",
                 r.get("refused") and r.get("status") == "confirm_required", {"status": r.get("status"), "reason": r.get("reason")})
            f.write_text(json.dumps({"last_real_input_epoch": time.time(), "watcher_alive_epoch": time.time()}), encoding="utf-8")
            r = await call(s, "cig_do", app=app, action_id=again["id"], confirm=note)
            step("(person active) with confirm it goes through", r.get("ok"), {"ok": r.get("ok"), "reason": r.get("reason")})
    plog = Path(a.instance) / "plugins" / "data" / "ApocryphaAgentControl" / "log.txt"
    tail = plog.read_text(encoding="utf-8", errors="replace").splitlines()[-40:] if plog.is_file() else []
    hit = next((ln for ln in reversed(tail) if note in ln), None)
    step("the confirm note is in MO2 Agent Control's own log, beside the press", bool(hit), hit or tail[-3:])


def scrub(text, instance):
    """The record names no folder of the machine it ran on: the instance path, written with either slash and with or
    without JSON's doubled backslashes, becomes <instance>."""
    parts = [re.escape(p) for p in re.split(r"[\\/]+", instance.rstrip("\\/")) if p]
    return re.sub(r"[\\/]+".join(parts), "<instance>", text, flags=re.I)


def write(a, log):
    out = REPO / "docs" / "proofs" / "M3-mo2-host.md"
    ok = bool(steps) and all(x["ok"] for x in steps) and len(steps) >= 40
    lines = [f"# M3 proof - Modlist Manager's window inside MO2, driven through CIG's MCP server ({datetime.datetime.now():%Y-%m-%d %H:%M})",
             "", f"Result: **{'PASS' if ok else 'FAIL'}** - {sum(x['ok'] for x in steps)}/{len(steps)} steps.", "",
             "Generated by `tools/prove_m3.py`, which talks MCP over stdio to `cig_server.py` and picks actions by the labels",
             "CIG generated. The target is a scratch Mod Organizer 2 running MO2 Agent Control (the host channel) and MO2",
             "Modlist Manager (the window). CIG holds no code for either window: `cig/adapters/host_mo2.py` turns the",
             "plugin's `ui_tree` into nodes and `library/rules/uia.json` - the rules that drove Notepad - produces the",
             "actions. No mouse or keyboard input was sent and no window was raised.", "",
             "| # | Step | Result | Detail |", "|---|---|---|---|"]
    for i, x in enumerate(steps, 1):
        d = scrub(json.dumps(x["detail"], ensure_ascii=False, default=str).replace("|", "\\|"), a.instance)[:260]
        lines.append(f"| {i} | {x['step']} | {'PASS' if x['ok'] else 'FAIL'} | {d} |")
    lines += ["", "## Action log entries for the run (from `cig_log`)", "", "```"]
    for e in log or []:
        if e.get("adapter") and not str(e.get("adapter")).startswith("host:"):
            continue
        lines.append(scrub(json.dumps({k: e.get(k) for k in ("time", "app", "action", "action_id", "kind", "ok", "refused",
                                                              "reason", "backup")}, ensure_ascii=False, default=str),
                           a.instance)[:400])
    lines.append("```")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(("PASS" if ok else "FAIL"), f"{sum(x['ok'] for x in steps)}/{len(steps)} ->", out)
    return ok


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--instance", required=True, help="the SCRATCH MO2 instance folder (MO2 already running on it)")
    p.add_argument("--profile", default="Default")
    a = p.parse_args(argv)
    low = os.path.normcase(os.path.abspath(a.instance))
    if "scratch" not in low and "_work" not in low and not os.environ.get("CIG_PROOF_ANY_INSTANCE"):
        print("refused: this proof presses Apply. Run it on a scratch instance (a path holding 'scratch' or '_work').")
        return 2
    log = asyncio.run(run(a))
    return 0 if write(a, log) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
