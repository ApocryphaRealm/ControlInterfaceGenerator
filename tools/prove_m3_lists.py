"""M3 follow-up proof: MO2's own lists and menus through CIG's engine and the host adapter (no mouse, no keyboard).

  py -3 tools/prove_m3_lists.py --instance "<SCRATCH MO2 instance folder>"

MO2 must be running on a SCRATCH instance with MO2 Agent Control 1.1.0 (the build with ui_items / ui_menus) and MO2
Modlist Manager. The script: reads the generated actions (rows of the mod list as set_checked, the menus as one `menu`
action), unticks ONE enabled mod and ticks it again through `do` with the read-back verified, reads the list's rows,
opens the Modlist Manager window from its menu path and closes it. Exit 0 when every step passed; it stops at the
first failed step and leaves MO2 as it is.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from cig.adapters.host_mo2 import HostMo2Adapter  # noqa: E402
from cig.engine import Engine  # noqa: E402

MM = "MO2 Modlist Manager"
steps = []


class Stop(Exception):
    pass


def step(name, ok, detail=""):
    steps.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + " - " + json.dumps(detail, ensure_ascii=False, default=str)[:380], flush=True)
    if not ok:
        raise Stop(name)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--instance", required=True)
    a = ap.parse_args(argv)
    low = os.path.normcase(os.path.abspath(a.instance))
    if "scratch" not in low and "_work" not in low:
        print("refused: this unticks a mod. Run it on a scratch instance (a path holding 'scratch' or '_work').")
        return 2
    app = "mo2:" + a.instance
    e = Engine([HostMo2Adapter()])
    try:
        acts = e.actions(app)["actions"]
        rows = [x for x in acts if x["action"] == "set_checked" and " TreeItem " in x["label"]]
        bar = next((x for x in acts if x["action"] == "menu"), None)
        reader = next((x for x in acts if x["action"] == "list_items" and "'modList'" in x["label"]), None)
        step("the mod list's rows are typed actions, with no MO2 rule", len(rows) >= 1 and bool(reader),
             {"set_checked rows": len(rows), "sample": [x["label"] for x in rows[:4]], "rules": sorted({x["rule"] for x in acts})})
        step("the menus are one 'menu' action with paths", bool(bar) and len(bar["input_schema"]["properties"]["path"].get("examples", [])) >= 3,
             bar and bar["input_schema"]["properties"]["path"].get("examples", [])[:10])

        tree = {t["id"]: t for t in e.tree(app, max_nodes=2000)["elements"]}
        on = next((x for x in rows if tree.get(x["element"], {}).get("toggle_state") == "On"
                   and not tree[x["element"]]["name"].endswith("_separator")), None)
        step("an enabled mod row was found", bool(on), on and on["label"])
        r = e.do(app, on["id"], {"checked": False})
        step("untick it through cig do: done and verified by read-back", r.get("ok") and r.get("verified") is True
             and r["changed"]["after"].get("toggle_state") == "Off", {k: r.get(k) for k in ("ok", "verified", "reason", "backup")})
        r = e.do(app, on["id"], {"checked": True})
        step("tick it again: verified", r.get("ok") and r.get("verified") is True and r["changed"]["after"].get("toggle_state") == "On",
             {k: r.get(k) for k in ("ok", "verified", "reason")})

        r = e.do(app, reader["id"], {})
        d = r.get("detail") or {}
        step("list_items reads the rows with their columns", r.get("ok") and len(d.get("rows") or []) >= 1,
             {"columns": d.get("columns"), "rows": len(d.get("rows") or []), "detail": d.get("detail")})

        paths = bar["input_schema"]["properties"]["path"].get("examples", [])
        path = next((p for p in paths if "Modlist Manager" in p), None)
        step("a menu path to the Modlist Manager window exists", bool(path), paths[:20])
        r = e.do(app, bar["id"], {"path": path})
        d = r.get("detail") or {}
        step("choosing it opens the window: returned false, the window described", r.get("ok") and d.get("returned") is False
             and (d.get("modal_open") or {}).get("title") == MM, {"path": path, "returned": d.get("returned"), "modal": d.get("modal_open")})
        acts = e.actions(app)["actions"]
        step("with it open, the main window's rows and menus are not offered",
             not any(x["action"] == "menu" for x in acts) and not any(" TreeItem " in x["label"] and x["action"] == "set_checked" for x in acts),
             sorted({x["label"] for x in acts})[:6])
        close = next((x for x in acts if x["action"] == "invoke" and x["label"].endswith("'Close'")), None)
        r = e.do(app, close["id"], {}) if close else {"reason": "no Close button"}
        step("close it", r.get("ok") and (r.get("detail") or {}).get("returned") is True, {k: r.get(k) for k in ("ok", "reason")})
        step("the main window is back with its rows", any(x["action"] == "set_checked" and " TreeItem " in x["label"]
                                                          for x in e.actions(app)["actions"]), "")
    except Stop:
        pass
    ok = bool(steps) and all(steps)
    print(("PASS" if ok else "FAIL") + f": {sum(steps)}/{len(steps)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
