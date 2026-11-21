"""Survey one program for CIG, READ-ONLY: start it, detect what it is built with, read its UI tree once, say how much
of it CIG could act on, then ask it to close - and write nothing into it.

  py -3 tools/survey_tool.py --name <short name> --exe <path> [--wait 8] [--out DIR] [-- args...]

What is recorded (one JSON file per program, <out>/<name>.json, plus a one-screen summary on the console):
  version       the exe's file / product version
  detect        the detector's ranked frameworks and adapters (cig/detect.py)
  windows       every top-level window's title, class and whether it is modal
  tree          how many elements, per control type: count, how many have a Name, how many an AutomationId, patterns
  actions       the typed actions library/rules/uia.json generates, counted per action
  opaque        elements CIG can see but not act on or read: Pane / Custom / Image with no name, no pattern, no child
  containers    lists, trees, tables and data grids with how many items UIA shows of each (a record tree or a mod list)
  busy          CPU use while idle in front of us - a program that starts working on its own shows here
  close         how the close went: gone, or what stayed open (a 'save?' question is answered Don't save / No, never
                Save; a question with no such answer is left open and reported)

Nothing is clicked, typed or chosen except that closing question. The program is started by cig.launch (unelevated,
refused while the person is using the machine) and only ever asked to close (WM_CLOSE); it is never killed.
"""
import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import psutil  # noqa: E402

from cig import detect, launch, locator, rules  # noqa: E402
from cig.adapters.uia import UiaAdapter  # noqa: E402
from cig.engine import Engine  # noqa: E402

NO_SAVE = ("don't save", "dont save", "do not save", "no", "discard", "close without saving", "exit without saving",
           "don't apply", "no to all")
CONTAINERS = ("List", "Tree", "DataGrid", "Table", "TreeView", "ListView")
DEAD = ("Pane", "Custom", "Image", "Group")


def plain(s):
    return str(s or "").replace("&", "").strip().lower()


def tree_stats(windows):
    by = collections.defaultdict(lambda: {"count": 0, "named": 0, "aid": 0, "patterns": collections.Counter()})
    opaque, containers, total, fw = 0, [], 0, collections.Counter()
    for node, _loc, _p, _w in locator.walk(windows):
        total += 1
        ct = node.get("control_type") or "Custom"
        b = by[ct]
        b["count"] += 1
        b["named"] += bool(node.get("name"))
        b["aid"] += bool(node.get("automation_id"))
        for p in node.get("patterns") or []:
            b["patterns"][p] += 1
        if node.get("framework_id"):
            fw[node["framework_id"]] += 1
        kids = node.get("children") or []
        if ct in DEAD and not kids and not node.get("name") and not node.get("patterns"):
            opaque += 1
        if ct in CONTAINERS:
            items = [k for k in kids if k.get("control_type") in ("ListItem", "TreeItem", "DataItem", "Custom", "Header")]
            containers.append({"type": ct, "name": (node.get("name") or "")[:50], "aid": node.get("automation_id") or "",
                               "items": len(items), "sample": [(k.get("name") or "")[:40] for k in items[:4]],
                               "item_patterns": sorted({p for k in items[:20] for p in (k.get("patterns") or [])})})
    types = {k: {"count": v["count"], "named": v["named"], "aid": v["aid"], "patterns": dict(v["patterns"])}
             for k, v in sorted(by.items(), key=lambda kv: -kv[1]["count"])}
    named = sum(v["named"] for v in by.values())
    aid = sum(v["aid"] for v in by.values())
    return {"elements": total, "named_rate": round(named / total, 2) if total else 0,
            "aid_rate": round(aid / total, 2) if total else 0, "opaque": opaque, "framework_ids": dict(fw),
            "control_types": types, "containers": containers}


def describe_windows(windows):
    out = []
    for w in windows:
        buttons = [c.get("name") for c in (w.get("children") or []) if c.get("control_type") == "Button" and c.get("name")]
        out.append({"title": (w.get("name") or "")[:90], "class": w.get("class_name") or "", "modal": bool(w.get("is_modal")),
                    "children": len(w.get("children") or []), "buttons": buttons[:8]})
    return out


def cpu(pid, seconds=2.0):
    try:
        procs = [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True)
        for p in procs:
            p.cpu_percent(None)
        time.sleep(seconds)
        return round(sum(p.cpu_percent(None) for p in procs if p.is_running()), 1)
    except psutil.Error:
        return None


def close_politely(e, pid, app, log):
    """WM_CLOSE; a closing question is answered with a 'do not save' button when it has one, else left and reported."""
    r = launch.close(pid, 12)
    log.append({"close": {k: r.get(k) for k in ("ok", "closed", "still_open")}})
    tries = 0
    while not r.get("closed") and tries < 3 and psutil.pid_exists(pid):
        tries += 1
        try:
            acts = e.actions(app)["actions"]
        except Exception as exc:  # noqa: BLE001
            log.append({"closing_question": f"unreadable: {exc}"})
            break
        dialogs = [a for a in acts if a["action"] == "answer_dialog"]
        answered = False
        for d in dialogs:
            options = d["input_schema"]["properties"]["button"].get("enum") or []
            pick = next((o for o in options if plain(o) in NO_SAVE), None)
            log.append({"closing_question": d["label"], "buttons": options, "answer": pick})
            if pick:
                res = e.do(app, d["id"], {"button": pick}, confirm="survey: closing without saving, as the survey's rule says")
                log.append({"answered": res.get("ok"), "reason": res.get("reason")})
                answered = bool(res.get("ok"))
                break
        if not answered:
            break
        time.sleep(1.5)
        r = launch.close(pid, 10) if psutil.pid_exists(pid) else {"closed": True, "ok": True}
        log.append({"close": {k: r.get(k) for k in ("ok", "closed", "still_open")}})
    return not psutil.pid_exists(pid)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--wait", type=float, default=8.0, help="seconds to let the window settle before reading it")
    ap.add_argument("--out", default=str(REPO / "var" / "survey"))
    ap.add_argument("--press", action="append", default=[], help="a button to press before reading the tree, to get past a "
                    "start-up dialog to the main window: 'Dialog title|Button' answers a modal dialog, 'Button' presses a "
                    "button (repeatable, in order). Loading is not writing; never use it for a button that changes files")
    ap.add_argument("--wait2", type=float, default=20.0, help="seconds to wait after the presses")
    ap.add_argument("--attach", type=int, default=0, help="survey this pid instead of starting --exe: the real window "
                    "of a program whose launcher (started by an earlier run of this script) handed over and exited")
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    args = [x for x in a.rest if x != "--"]
    e = Engine([UiaAdapter()])
    out = {"name": a.name, "exe": a.exe, "args": args, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
           "version": detect.file_version(a.exe)}
    if a.attach:
        r = {"ok": psutil.pid_exists(a.attach), "pid": a.attach, "via": "attached to the process this survey's launcher run started",
             "reason": "" if psutil.pid_exists(a.attach) else "no such process"}
    else:
        # start it from ITS OWN folder: a launched program inherits the working folder, and tools take it for home
        # (Wabbajack's launcher unpacked its update into the folder this script was run from, 2026-11-20)
        os.chdir(str(Path(a.exe).resolve().parent))
        r = launch.launch(a.exe, args, policy=e.policy, wait_s=90)
    out["launch"] = {k: r.get(k) for k in ("ok", "pid", "refused", "reason", "via")}
    if not r.get("ok"):
        print(json.dumps(out["launch"]))
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / f"{a.name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        return 1
    pid = r["pid"]
    e.register_launch(pid, Path(a.exe).name)
    app = str(pid)
    log = []
    try:
        time.sleep(a.wait)
        pressed = []
        for spec in a.press:
            acts = e.actions(app)["actions"]
            if "|" in spec:
                title, button = spec.split("|", 1)
                hit = next((x for x in acts if x["action"] == "answer_dialog" and x["label"].endswith(f"'{title}'")), None)
                res = e.do(app, hit["id"], {"button": button}, confirm="survey: past the start-up dialog, loading only") if hit else {"reason": "no such dialog"}
            else:
                hit = next((x for x in acts if x["action"] == "invoke" and x["label"].endswith(f"'{spec}'")), None)
                res = e.do(app, hit["id"], {}, confirm="survey: past the start-up dialog, loading only") if hit else {"reason": "no such button"}
            pressed.append({"press": spec, "ok": res.get("ok"), "reason": res.get("reason")})
            time.sleep(2.0)
        if a.press:
            out["pressed"] = pressed
            time.sleep(a.wait2)
        out["busy_cpu_percent"] = cpu(pid)
        try:
            d = detect.detect(pid)
            top = (d.get("frameworks") or d.get("ranked") or [{}])[0] if isinstance(d.get("frameworks") or d.get("ranked"), list) else {}
            out["detect"] = {k: v for k, v in d.items() if k != "process"}
            out["detect"]["process"] = {k: v for k, v in (d.get("process") or {}).items() if k != "exe"}
            out["detect"]["framework"] = d.get("framework") or top.get("framework") or top.get("name")
        except Exception as exc:  # noqa: BLE001
            out["detect"] = {"error": str(exc)}
        try:
            snap = e._snapshot(*e.resolve(app))
            out["windows"] = describe_windows(snap["windows"])
            out["texts"] = [str(n.get("name") or n.get("value") or "")[:300] for n, _l, _p, _w in locator.walk(snap["windows"])
                            if n.get("control_type") in ("Text", "Edit", "Document") and (n.get("name") or n.get("value"))][:25]
            out["tree"] = tree_stats(snap["windows"])
            acts = rules.actions_for(snap["windows"])
            out["actions"] = dict(collections.Counter(x["action"] for x in acts))
            out["action_labels_sample"] = [x["label"] for x in acts[:40]]
            out["menu_paths"] = len(snap.get("menu_paths") or [])
        except Exception as exc:  # noqa: BLE001
            out["tree"] = {"error": str(exc)}
        out["busy_cpu_percent_after"] = cpu(pid, 1.5)
    finally:
        out["closed"] = close_politely(e, pid, app, log)
        out["close_log"] = log
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / f"{a.name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    t = out.get("tree") or {}
    print(json.dumps({"name": a.name, "version": (out["version"] or {}).get("product_version") or (out["version"] or {}).get("file_version"),
                      "detect": json.dumps({k: v for k, v in out.get("detect", {}).items() if k != "process"}, default=str)[:420],
                      "windows": [(w["title"], w["class"], w["modal"]) for w in out.get("windows", [])][:6],
                      "elements": t.get("elements"), "named": t.get("named_rate"), "aid": t.get("aid_rate"),
                      "opaque": t.get("opaque"), "fw_ids": t.get("framework_ids"),
                      "types": {k: v["count"] for k, v in list((t.get("control_types") or {}).items())[:12]},
                      "containers": t.get("containers"), "actions": out.get("actions"), "menus": out.get("menu_paths"),
                      "cpu": [out.get("busy_cpu_percent"), out.get("busy_cpu_percent_after")],
                      "closed": out["closed"], "close_log": log, "tree_error": t.get("error")}, ensure_ascii=False, default=str)[:3800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
