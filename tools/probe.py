"""M6 probe harness (plan 2.3 source 2): what a framework REALLY does, measured on a running program.

  py -3 tools/probe.py --framework <fw> --name <probe name> --launch <exe> [args...] [--actions] [--cdp FLAG]
  py -3 tools/probe.py --framework <fw> --name <probe name> --app <pid|exe>                  (read-only)

Everything goes through CIG's engine, so the safety layer applies to the probe too. It records, per control type:
how many were seen, which patterns were present, how often a Name / AutomationId was set, and how that compares with
the spec table (library/uia/control-types.json: a 'supported' pattern missing, a 'not_supported' one present).
With --actions (ONLY on CIG's own reference galleries) every generated action of a probe-safe kind is tried, read
back, and the element put back as it was; each result is recorded per control type and rule.
Output: library/probes/<fw>/<name>.json, and the framework entry's 'observed' list gets a summary + a probe source.
"""
import argparse
import collections
import datetime
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cig import config, launch, locator  # noqa: E402
from cig.adapters.cdp import CdpAdapter  # noqa: E402
from cig.adapters.uia import UiaAdapter  # noqa: E402
from cig.engine import Engine  # noqa: E402

SPEC = json.loads((config.LIBRARY_DIR / "uia" / "control-types.json").read_text(encoding="utf-8"))["control_types"]
SAFE = {"set_checked", "select", "set_text", "set_number", "choose", "expand"}   # probe-safe action kinds


def survey(windows):
    by = collections.defaultdict(lambda: {"count": 0, "patterns": collections.Counter(), "named": 0, "aid": 0,
                                          "framework_ids": collections.Counter()})
    for node, _loc, _p, _w in locator.walk(windows):
        ct = node.get("control_type") or "Custom"
        b = by[ct]
        b["count"] += 1
        b["named"] += bool(node.get("name"))
        b["aid"] += bool(node.get("automation_id"))
        for p in node.get("patterns") or []:
            b["patterns"][p] += 1
        if node.get("framework_id"):
            b["framework_ids"][node["framework_id"]] += 1
    out = {}
    for ct, b in sorted(by.items()):
        spec = SPEC.get(ct, {})
        present = {p for p, n in b["patterns"].items() if n}
        out[ct] = {"count": b["count"], "named_pct": round(100 * b["named"] / b["count"]),
                   "automation_id_pct": round(100 * b["aid"] / b["count"]),
                   "patterns": dict(b["patterns"].most_common()), "framework_ids": dict(b["framework_ids"]),
                   "spec_required_missing": sorted(set(spec.get("supported", [])) - present - {"Transform"}),
                   "spec_forbidden_present": sorted(set(spec.get("not_supported", [])) & present)}
    return out


def combo_options(e, app, element_id):
    """A collapsed combo box lists no options in the tree: open it, read its items, close it (UIA, own galleries)."""
    from cig import uiawalk
    import uiautomation as auto
    adapter, target = e.resolve(app)
    info = e._snapshot(adapter, target)["elements"].get(element_id)
    if not info or not hasattr(adapter, "_find_live"):
        return []

    def work():
        c = adapter._find_live(target, info["locator"])
        if c is None:
            return []
        try:
            ec = uiawalk.pattern(c, "ExpandCollapse")
        except LookupError:
            return []
        ec.Expand()
        time.sleep(0.4)
        from cig.adapters.uia import combo_items           # under the combo, or in its popup window (Avalonia)
        names = list(dict.fromkeys(x.Name for x in combo_items(c)))
        ec.Collapse()
        return names
    return uiawalk.run(work, timeout=20)


def try_actions(e, app, skip_under=()):
    results = []
    acts = e.actions(app)["actions"]
    snap = e._snapshot(*e.resolve(app))
    for a in acts:
        if a["action"] not in SAFE:
            continue
        loc = (snap["elements"].get(a["element"]) or {}).get("locator", "")
        if any(f'[aid="{s}"]' in loc or f'[name="{s}"]' in loc for s in skip_under):
            continue                    # the app's own chrome (e.g. a gallery's navigation pane): surveyed, not acted on
        before = e.read(app, a["element"]).get("state", {})
        if a["action"] == "choose" and not a["input_schema"]["properties"]["option"].get("enum"):
            opts = combo_options(e, app, a["element"])
            a["input_schema"]["properties"]["option"]["enum"] = opts
            if not opts:
                results.append({"rule": a["rule"], "action": "choose", "label": a["label"], "ok": False,
                                "verified": None, "refused": False,
                                "reason": "no options readable (the combo has no ExpandCollapse to open it)"})
                continue
        args = probe_args(a, before)
        if args is None:
            continue
        r = e.do(app, a["id"], args)
        rec = {"rule": a["rule"], "action": a["action"], "label": a["label"], "args": args, "ok": bool(r.get("ok")),
               "verified": r.get("verified"), "refused": r.get("refused"), "reason": r.get("reason")}
        undo = undo_args(a, before)                         # put the element back as it was
        if r.get("ok") and undo is not None:
            u = e.do(app, a["id"], undo)
            rec["restored"] = bool(u.get("ok"))
        results.append(rec)
        time.sleep(0.15)
    return results


def probe_args(a, before):
    act = a["action"]
    props = a["input_schema"].get("properties", {})
    if act == "set_checked":
        return {"checked": before.get("toggle_state") != "On"}
    if act == "select":
        return {} if not before.get("selected") else None
    if act == "set_text":
        return {"text": "CIG probe"} if not str(before.get("value") or "").strip() else None
    if act == "set_number":
        lo, hi = props["value"].get("minimum", 0), props["value"].get("maximum", 10)
        cur = (before.get("range") or {}).get("value", lo)
        return {"value": hi if cur != hi else lo}
    if act == "choose":
        opts = props["option"].get("enum") or []
        return {"option": next((o for o in opts if o != before.get("value")), None)} if len(opts) > 1 else None
    if act == "expand":
        return {"expanded": before.get("expand_state") != "Expanded"}
    return None


def undo_args(a, before):
    act = a["action"]
    if act == "set_checked":
        return {"checked": before.get("toggle_state") == "On"}
    if act == "set_number" and (before.get("range") or {}).get("value") is not None:
        return {"value": before["range"]["value"]}
    if act == "choose" and before.get("value"):
        return {"option": before["value"]}
    if act == "expand":
        return {"expanded": before.get("expand_state") == "Expanded"}
    if act == "set_text":
        return {"text": ""}
    return None


def summarise(results):
    by = collections.defaultdict(lambda: {"tried": 0, "ok": 0, "verified": 0, "refused": 0})
    for r in results:
        k = f"{r['rule']}:{r['action']}"
        by[k]["tried"] += 1
        by[k]["ok"] += r["ok"]
        by[k]["verified"] += bool(r["verified"])
        by[k]["refused"] += bool(r["refused"])
    return dict(by)


def record(fw, name, data):
    d = config.LIBRARY_DIR / "probes" / fw
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    p = config.LIBRARY_DIR / "frameworks" / f"{fw}.json"
    e = json.loads(p.read_text(encoding="utf-8"))
    tag = f"probe:{data['date']} {name} (tools/probe.py{' --actions' if data.get('actions') else ''})"
    e["source"] = [s for s in e["source"] if not (s.startswith("probe:") and f" {name} " in s)] + [tag]
    summ = {"probe": name, "date": data["date"], "app": data["app"], "control_types": {
        ct: {"count": v["count"], "patterns": sorted(v["patterns"]), "named_pct": v["named_pct"],
             "automation_id_pct": v["automation_id_pct"]} for ct, v in data["survey"].items()}}
    if data.get("action_summary"):
        summ["actions"] = data["action_summary"]
    e["probed"] = [x for x in e.get("probed", []) if x.get("probe") != name] + [summ]
    # spec deviations become quirks, each with its probe as the source (plan 2.3: an entry never changes silently)
    quirks = {q["id"]: q for q in e.get("quirks", [])}
    for ct, v in data["survey"].items():
        for pat in v["spec_required_missing"]:
            qid = f"{fw}-{ct.lower()}-no-{pat.lower()}"
            quirks[qid] = {"id": qid, "source": f"probe:{data['date']} {name}",
                           "text": f"{ct} does not expose the {pat} pattern the UIA spec requires (seen on "
                                   f"{v['count']} of them; patterns present: {sorted(v['patterns'])})."}
        for pat in v["spec_forbidden_present"]:
            qid = f"{fw}-{ct.lower()}-has-{pat.lower()}"
            quirks[qid] = {"id": qid, "source": f"probe:{data['date']} {name}",
                           "text": f"{ct} exposes {pat}, which the UIA spec says it must not."}
    if quirks:
        e["quirks"] = list(quirks.values())
    p.write_text(json.dumps(e, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--app")
    ap.add_argument("--launch", nargs=argparse.REMAINDER)
    ap.add_argument("--actions", action="store_true")
    ap.add_argument("--cdp")
    ap.add_argument("--wait", type=float, default=3.0)
    ap.add_argument("--navigate", action="append", help="label to select before probing (repeatable, in order)")
    ap.add_argument("--skip-under", action="append", help="AutomationId or Name of a container whose elements are surveyed but not acted on (repeatable)")
    a = ap.parse_args()
    e = Engine([CdpAdapter(), UiaAdapter()])
    pid = None
    if a.launch:
        r = launch.launch(a.launch[0], a.launch[1:], policy=e.policy, cdp=bool(a.cdp), profile_flag=a.cdp, wait_s=60)
        if not r.get("ok"):
            print("launch failed:", r.get("reason"))
            return 1
        pid = r["pid"]
        e.register_launch(pid, Path(a.launch[0]).name)
        app = str(pid)
        time.sleep(a.wait)
    else:
        app = a.app
    for label in a.navigate or []:
        # reach a page first (a gallery's navigation): select / invoke the element with this label, then let it load
        acts = e.actions(app)["actions"]
        nav = next((x for x in acts if x["action"] in ("select", "invoke") and x["label"].endswith(f"'{label}'")), None)
        if not nav:
            print(f"navigate: no '{label}' to select")
            break
        print("navigate:", label, e.do(app, nav["id"], {}).get("ok"))
        time.sleep(2.5)
    try:
        target = e.resolve(app)[1]
        snap = e._snapshot(*e.resolve(app))
        data = {"framework": a.framework, "name": a.name, "date": datetime.date.today().isoformat(),
                "app": {"exe": target.exe, "title": target.title, "adapter": target.adapter},
                "elements": len(snap["elements"]), "survey": survey(snap["windows"]), "actions": a.actions}
        if a.actions:
            res = try_actions(e, app, a.skip_under or [])
            data["action_results"] = res
            data["action_summary"] = summarise(res)
        record(a.framework, a.name, data)
        print(json.dumps({"elements": data["elements"], "control_types": len(data["survey"]),
                          "actions": data.get("action_summary")}, indent=1)[:2500])
    finally:
        if pid:
            print("close:", launch.close(pid, 20).get("ok"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
