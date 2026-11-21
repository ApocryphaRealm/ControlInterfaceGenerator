"""The MO2 host adapter (M3) through the engine and the MCP tool functions, against a fake channel that replays what a
live MO2 answered (tests/fixtures/host-mo2/, cut from the 2026-11-20 run of MO2 Agent Control 1.1.0's window commands by
tools/make_host_fixtures.py). The fake finds a control the way the plugin does - a locator that matches two controls
is an error - so the indexes the adapter sends are checked, not assumed."""
import copy
import json

import pytest

from cig import actionlog, server
from cig.adapters.host_mo2 import HostMo2Adapter, host_locator
from cig.engine import Engine

from conftest import REPO

FX = REPO / "tests" / "fixtures" / "host-mo2"
APP = "mo2:X:/MO2"
MAIN = "MainWindow"
MM = "MO2 Modlist Manager"


def load(name):
    return json.loads((FX / f"{name}.json").read_text(encoding="utf-8"))


class FakeMo2:
    """MO2 with Modlist Manager, as a state machine: main -> mm (the tool window, itself a modal) -> question / restore."""

    def __init__(self):
        self.trees = {n: load(n) for n in ("main", "mm", "question", "restore")}
        self.info = load("info")
        self.state = "main"
        self.busy = False
        # lists and menus (plugin 1.1.0's second half): the recorded run predates them, so the fake carries its own
        self.info["reads"] = self.info["reads"] + ["ui_items", "ui_menus"]
        self.info["writes"] = self.info["writes"] + ["ui_item", "ui_menu"]
        self.trees["main"]["controls"].append({"kind": "view", "class": "QTreeView", "name": "modList", "enabled": True,
                                               "visible": True, "rows": 4, "columns": 2, "tree": True, "where": ""})
        self.rows = [{"row": 0, "cells": ["Alpha", "0"], "checked": True}, {"row": 1, "cells": ["Bravo", "1"], "checked": False},
                     {"row": 2, "cells": ["Armour_separator", "2"], "children": True, "expanded": False},
                     {"row": 3, "cells": ["Charlie", "3"], "checked": False}]
        self.entries = [{"path": "File", "enabled": True, "menu": True}, {"path": "File > Install Mod...", "enabled": True},
                        {"path": "Tools", "enabled": True, "menu": True},
                        {"path": "Tools > Tool Plugins", "enabled": True, "menu": True},
                        {"path": "Tools > Tool Plugins > MO2 Modlist Manager", "enabled": True},
                        {"path": "Tools > Remove orphans", "enabled": True},
                        {"path": "View > Log", "enabled": True, "checked": False}, {"path": "Refresh", "enabled": True}]
        self.menu_chosen = []
        self.calls, self.confirms, self.answers = [], [], []

    # -- the plugin's own locate(): exact, and never a guess
    def _locate(self, a):
        controls = [c for c in self.trees[self.state]["controls"] if c["kind"] != "label"]
        win = a.get("window")
        if self.state != "main" and win and win not in (self.trees[self.state]["window"]["title"],):
            raise ValueError("a modal dialog is open - answer it first")
        if self.state == "main" and win not in (None, MAIN, self.trees["main"]["window"]["title"]):
            raise ValueError(f"no visible window titled or named {win!r}")
        hits = []
        for c in controls:
            if a.get("kind") and c["kind"] != a["kind"]:
                continue
            if a.get("name") and c.get("name") != a["name"]:
                continue
            t = a.get("text")
            if t and c.get("text", c.get("tooltip", "")) != t and c.get("tooltip", "") != t:
                continue
            hits.append(c)
        if not hits:
            raise ValueError("no visible control matches")
        if a.get("index") is not None:
            return hits[a["index"]]
        if len(hits) > 1:
            raise ValueError(f"{len(hits)} widgets match - nothing was done")
        return hits[0]

    def _modal(self):
        return copy.deepcopy(self.trees[self.state]["modal"]) if self.state != "main" else None

    def __call__(self, instance, cmd, args, confirm):
        self.calls.append((cmd, dict(args), confirm))
        assert instance == "X:/MO2"
        try:
            return self._handle(cmd, args, confirm)
        except ValueError as e:
            return {"ok": False, "error": f"ValueError: {e}"}

    def _handle(self, cmd, args, confirm):
        if cmd == "info":
            return dict(self.info, in_use=self.busy)
        if cmd == "ui_items":
            if self.state != "main" or args.get("name") != "modList":
                raise ValueError("no visible control matches")
            start, limit = args.get("start", 0), args.get("limit", 100)
            rows = copy.deepcopy(self.rows[start:start + limit])
            nxt = start + limit if start + limit < len(self.rows) else None
            return {"ok": True, "view": {"kind": "view", "name": "modList", "tree": True}, "total": len(self.rows), "start": start,
                    "columns": [{"column": 0, "title": "Mod Name", "hidden": False}, {"column": 1, "title": "Priority", "hidden": False}],
                    "rows": rows, "next": nxt}
        if cmd == "ui_menus":
            if self.state != "main":
                return {"ok": True, "entries": [], "total": 0, "truncated": False}
            return {"ok": True, "entries": copy.deepcopy(self.entries), "total": len(self.entries), "truncated": False}
        if cmd == "ui_tree":
            if args.get("window") in (MAIN,) and self.state != "main":
                return copy.deepcopy(self.trees["main"])
            return copy.deepcopy(self.trees[self.state])
        if self.busy and not confirm:
            return {"ok": False, "refused": True, "error": "MO2 is in use (MO2 is in front and the last input was 0.2 min "
                    "ago (activity file)) - send confirm with a note saying who approved this"}
        if confirm:
            self.confirms.append((cmd, confirm))
        if cmd == "ui_item":
            if self.state != "main" or args.get("name") != "modList":
                raise ValueError("a modal dialog is open - answer it first")
            hits = [r for r in self.rows if ("row" in args and r["row"] == args["row"]) or
                    ("match" in args and r["cells"][0] == args["match"])]
            if len(hits) != 1:
                raise ValueError(f"{len(hits)} rows match")
            r = hits[0]
            was = copy.deepcopy(r)
            act = args["action"]
            if act in ("check", "uncheck"):
                if "checked" not in r:
                    raise ValueError("that row has no box to tick")
                r["checked"] = act == "check"
            elif act == "select":
                for x in self.rows:
                    x.pop("selected", None)
                r["selected"] = True
            elif act in ("expand", "collapse"):
                r["expanded"] = act == "expand"
            return {"ok": True, "action": act, "was": was, "row": copy.deepcopy(r), "applied": True, "returned": True,
                    "modal": None, "backup": "X:/MO2/backups/b3"}
        if cmd == "ui_menu":
            e = next((x for x in self.entries if x["path"] == args.get("path")), None)
            if e is None:
                raise ValueError("no menu entry")
            self.menu_chosen.append(e["path"])
            if e["path"].endswith("MO2 Modlist Manager"):
                self.state = "mm"
                return {"ok": True, "chosen": e, "returned": False, "modal": self._modal()}
            if "checked" in e:
                e["checked"] = not e["checked"]
            return {"ok": True, "chosen": e, "returned": True, "modal": None, **({"checked": e["checked"]} if "checked" in e else {})}
        if cmd == "ui_click":
            c = self._locate(args)
            if not c["enabled"]:
                raise ValueError("disabled")
            nxt = {("main", "MO2 Modlist Manager"): "mm", ("mm", "Apply"): "question", ("mm", "Restore backup..."): "restore",
                   ("mm", "Close"): "main"}.get((self.state, c.get("text")))
            opened = nxt in ("mm", "question", "restore")
            if nxt:
                self.state = nxt
            return {"ok": True, "clicked": c, "returned": not opened, "modal": self._modal(), "backup": "X:/MO2/backups/b1"}
        if cmd == "ui_answer_modal":
            if self.state not in ("question", "restore", "mm"):
                raise ValueError("no modal dialog is open")
            was = self._modal()
            if args.get("expect") and args["expect"] not in was["title"] + " " + was.get("text", ""):
                raise ValueError("the open dialog is not the expected one")
            texts = [b["text"] for b in was["buttons"]] + [c.get("text") for c in self.trees[self.state]["controls"]
                                                           if c["kind"] == "button"]
            if args.get("text") not in texts:
                raise ValueError("the dialog has no such button")
            self.answers.append((self.state, args["text"]))
            if self.state in ("question", "restore"):
                self.state = "mm"
            elif args["text"] == "Close":
                self.state = "main"
            return {"ok": True, "answered": was, "pressed": args["text"], "closed": True, "returned": True,
                    "modal": self._modal(), "backup": "X:/MO2/backups/b2"}
        if cmd == "ui_set":
            c = self._locate(args)
            v = args["value"]
            if c["kind"] == "tabs":
                c["index"], c["value"] = c["items"].index(v), v
            elif c["kind"] == "combo":
                if v not in c["items"]:
                    raise ValueError(f"the combo box has no item {v!r}")
                c["value"], c["index"] = v, c["items"].index(v)
            elif c["kind"] in ("edit", "spin"):
                c["value"] = v
            else:
                c["checked"] = bool(v)
            return {"ok": True, "set": c, "asked": v, "value": v, "applied": True, "returned": True, "modal": self._modal()}
        raise ValueError(f"unknown command {cmd!r}")


@pytest.fixture
def mo2():
    return FakeMo2()


@pytest.fixture
def eng(mo2):
    e = Engine([HostMo2Adapter(transport=mo2, instances=lambda: ["X:/MO2"])])
    server.set_engine(e)
    yield e
    server.set_engine(None)


def act(eng, action, label, ctype=None):
    hits = [a for a in eng.actions(APP)["actions"]
            if a["action"] == action and f"'{label}'" in a["label"] and (ctype is None or f" {ctype} " in a["label"])]
    assert len(hits) == 1, (action, label, [h["label"] for h in hits])
    return hits[0]


def test_resolves_only_its_own_references(eng):
    ad = eng.adapters[0]
    assert ad.resolve("ModOrganizer.exe") is None and ad.resolve("4242") is None and ad.resolve("notepad") is None
    t = ad.resolve("mo2")
    assert t.exe == "ModOrganizer.exe" and t.adapter == "host:mo2-agent-control" and t.pid == 4242
    assert ad.resolve(APP).key == t.key


def test_an_old_plugin_is_refused_with_the_reason(mo2):
    mo2.info["version"], mo2.info["reads"] = "1.0.0", ["info"]
    with pytest.raises(Exception, match="1.1.0 or newer"):
        HostMo2Adapter(transport=mo2, instances=lambda: ["X:/MO2"]).resolve("mo2")


def test_main_window_becomes_typed_actions_with_no_mo2_rule(eng):
    acts = eng.actions(APP)["actions"]
    labels = {a["label"] for a in acts}
    assert "invoke Button 'MO2 Modlist Manager'" in labels and "invoke Button 'Run'" in labels
    assert "choose ComboBox 'Profile'" in labels                       # the profile box, named by its label
    prof = act(eng, "choose", "Profile")
    assert prof["input_schema"]["properties"]["option"]["enum"] == ["<Manage...>", "Default"]
    assert "select TabItem 'Archives'" in labels
    assert not any("Update Mod Organizer" in a["label"] for a in acts)     # disabled: no action generated
    assert {a["rule"] for a in acts} <= {"button", "combo", "selectable", "edit-value", "text-read", "checkable",
                                         "keys-fallback", "range", "dialog-answer", "menu-bar", "tree-expand", "list-read"}


def test_every_generated_locator_names_exactly_one_control(mo2):
    for state in ("main", "mm", "question", "restore"):
        mo2.state = state
        controls = mo2.trees[state]["controls"]
        for c in controls:
            if c["kind"] == "label":
                continue
            loc = host_locator(c, controls, None)
            if loc is None:
                assert not c.get("name") and not c.get("text") and not c.get("tooltip")
                continue
            assert mo2._locate(loc) is c, (state, loc)


def test_modlist_manager_window_steps_end_to_end(eng, mo2, idle):
    """Plan 4.2's exit criterion, on the recorded program: open the window, Apply with each answer, the Restore
    question, Close - every step through cig_do, the modal driven by the reply's returned + modal fields."""
    idle(30)
    r = server.cig_do(APP, act(eng, "invoke", MM)["id"])
    assert r["ok"] and r["detail"]["returned"] is False and r["detail"]["modal_open"]["title"] == MM
    assert r["backup"] is None and r["detail"]["host_backup"]            # no profile folder in the fake: the plugin's own
    tree = server.cig_tree(APP)["elements"]
    assert [e["name"] for e in tree if e["type"] == "Window"] == [MM, mo2.trees["main"]["window"]["title"]]
    assert not any(e["name"] == "Run" for e in tree)                      # nothing behind the modal is listed
    assert any(e["type"] == "Text" and "Nothing is written until Apply" in e.get("value", "") for e in tree)

    r = server.cig_do(APP, act(eng, "select", "Plugins (2)")["id"])
    assert r["ok"] and r["verified"] is True

    for answer in ("Cancel", "Apply, leave plugins as they are", "Apply and switch them off"):
        r = server.cig_do(APP, act(eng, "invoke", "Apply", "Button")["id"])
        assert r["ok"] and r["detail"]["returned"] is False
        assert r["detail"]["modal_open"]["title"] == "Plugins would be switched off"
        dlg = act(eng, "answer_dialog", "Plugins would be switched off")
        assert set(dlg["input_schema"]["properties"]["button"]["enum"]) == {
            "Show Details...", "Apply and switch them off", "Apply, leave plugins as they are", "Cancel"}
        r = server.cig_do(APP, dlg["id"], {"button": answer})
        assert r["ok"] and r["verified"] is True, r
        sent = [c for c in mo2.calls if c[0] not in ("ui_tree", "info")][-1]
        assert sent[0] == "ui_answer_modal" and sent[1] == {"text": answer, "expect": "Plugins would be switched off"}
    assert [a for s, a in mo2.answers if s == "question"] == ["Cancel", "Apply, leave plugins as they are",
                                                              "Apply and switch them off"]

    r = server.cig_do(APP, act(eng, "invoke", "Restore backup...")["id"])
    assert r["ok"] and r["detail"]["modal_open"]["title"] == "Choose backup to restore"
    pick = act(eng, "choose", "Restore into the profile 'Default':")
    assert len(pick["input_schema"]["properties"]["option"]["enum"]) == 4
    r = server.cig_do(APP, act(eng, "answer_dialog", "Choose backup to restore")["id"], {"button": "Cancel"})
    assert r["ok"] and r["verified"] is True

    r = server.cig_do(APP, act(eng, "invoke", "Close")["id"])
    assert r["ok"] and r["detail"]["returned"] is True and "modal_open" not in r["detail"]
    assert mo2.state == "main" and any(e["name"] == "Run" for e in server.cig_tree(APP)["elements"])
    log = actionlog.tail(40)
    assert sum(1 for e in log if e.get("adapter") == "host:mo2-agent-control" and e.get("ok")) >= 9


def test_a_wrong_dialog_answer_is_refused_before_the_channel(eng, mo2, idle):
    idle(30)
    server.cig_do(APP, act(eng, "invoke", MM)["id"])
    server.cig_do(APP, act(eng, "invoke", "Apply", "Button")["id"])
    n = len(mo2.calls)
    r = server.cig_do(APP, act(eng, "answer_dialog", "Plugins would be switched off")["id"], {"button": "Yes"})
    assert not r["ok"] and "bad args" in r["reason"] and mo2.state == "question"
    assert not any(c[0] != "ui_tree" and c[0] != "info" for c in mo2.calls[n:])


def test_presence_cig_refuses_first_then_confirm_reaches_the_plugin(eng, mo2, idle):
    idle(1)                                                       # the person is at the machine
    a = act(eng, "invoke", MM)["id"]
    r = server.cig_do(APP, a)
    assert not r["ok"] and r["refused"] and r["status"] == "confirm_required" and mo2.state == "main"
    assert not any(c[0] == "ui_click" for c in mo2.calls)        # nothing reached MO2
    r = server.cig_do(APP, a, confirm="the owner said: open it")
    assert r["ok"] and mo2.state == "mm" and mo2.confirms == [("ui_click", "the owner said: open it")]


def test_the_plugins_own_in_use_refusal_is_a_refusal_not_a_failure(eng, mo2, idle):
    idle(30)                                                      # CIG sees the person away ...
    mo2.busy = True                                               # ... but MO2's own check disagrees
    r = server.cig_do(APP, act(eng, "invoke", MM)["id"])
    assert not r["ok"] and r["refused"] and r["status"] == "refused" and "MO2 is in use" in r["reason"]
    assert mo2.state == "main"
    assert actionlog.tail(1)[0]["refused"] is True


def test_a_stale_element_is_never_acted_on(eng, mo2, idle):
    idle(30)
    run = act(eng, "invoke", "Run")["id"]
    server.cig_do(APP, act(eng, "invoke", MM)["id"])              # a modal is now in front of the main window
    r = server.cig_do(APP, run)
    assert not r["ok"] and r["refused"] and "stale" in r["reason"]
    assert not any(c[0] == "ui_click" and c[1].get("name") == "startButton" for c in mo2.calls)


def test_value_sets_are_read_back(eng, mo2, idle):
    idle(30)
    r = server.cig_do(APP, act(eng, "choose", "Profile")["id"], {"option": "Default"})
    assert r["ok"] and r["verified"] is True
    sent = next(c for c in mo2.calls if c[0] == "ui_set")
    assert sent[1] == {"kind": "combo", "name": "profileBox", "window": MAIN, "value": "Default"}
    r = server.cig_do(APP, act(eng, "choose", "Profile")["id"], {"option": "Nope"})
    assert not r["ok"] and "bad args" in r["reason"]


# ---------------------------------------------------------------------------------------------- lists and menus
def test_mod_list_rows_are_typed_actions(eng, mo2):
    acts = eng.actions(APP)["actions"]
    labels = {a["label"]: a for a in acts}
    assert "set_checked TreeItem 'Alpha'" in labels and "set_checked TreeItem 'Bravo'" in labels
    assert "expand TreeItem 'Armour_separator'" in labels            # a row with rows under it and no box
    assert "list_items Tree 'modList'" in labels and "menu MenuBar 'Menus'" in labels
    tree = {e["name"]: e for e in server.cig_tree(APP)["elements"] if e["type"] == "TreeItem"}
    assert tree["Alpha"]["toggle_state"] == "On" and tree["Bravo"]["toggle_state"] == "Off"
    assert tree["Alpha"]["value"] == "Alpha | 0"


def test_ticking_a_mod_goes_through_the_plugins_model_command(eng, mo2, idle):
    idle(30)
    r = server.cig_do(APP, act(eng, "set_checked", "Bravo")["id"], {"checked": True})
    assert r["ok"] and r["verified"] is True and r["changed"]["after"]["toggle_state"] == "On"
    sent = [c for c in mo2.calls if c[0] == "ui_item"][-1]
    assert sent[1] == {"name": "modList", "window": MAIN, "action": "check", "match": "Bravo"}
    assert mo2.rows[1]["checked"] is True
    r = server.cig_do(APP, act(eng, "set_checked", "Alpha")["id"], {"checked": False})
    assert r["ok"] and mo2.rows[0]["checked"] is False


def test_opening_a_tree_row_and_reading_the_rows(eng, mo2, idle):
    idle(30)
    r = server.cig_do(APP, act(eng, "expand", "Armour_separator")["id"], {"expanded": True})
    assert r["ok"] and r["verified"] is True and mo2.rows[2]["expanded"] is True
    r = server.cig_do(APP, act(eng, "list_items", "modList")["id"])
    assert r["ok"] and r["detail"]["columns"] == ["Mod Name", "Priority"] and len(r["detail"]["rows"]) == 4
    assert not any(c[0] == "ui_item" for c in mo2.calls[-2:])        # a read sends no write


def test_a_menu_entry_without_a_toolbar_button(eng, mo2, idle):
    idle(30)
    bar = act(eng, "menu", "Menus")
    assert "Tools/Tool Plugins/MO2 Modlist Manager" in bar["input_schema"]["properties"]["path"]["examples"]
    r = server.cig_do(APP, bar["id"], {"path": "Tools/Tool Plugins/MO2 Modlist Manager"})
    assert r["ok"] and r["detail"]["returned"] is False and r["detail"]["modal_open"]["title"] == MM
    assert mo2.menu_chosen == ["Tools > Tool Plugins > MO2 Modlist Manager"] and mo2.state == "mm"


def test_menu_safety(eng, mo2, idle):
    idle(30)
    bar = act(eng, "menu", "Menus")["id"]
    r = server.cig_do(APP, bar, {"path": "Tools/Nope"})
    assert not r["ok"] and "no menu entry" in r["reason"] and mo2.menu_chosen == []
    r = server.cig_do(APP, bar, {"path": "Tools/Tool Plugins"})          # a submenu is not an entry to choose
    assert not r["ok"] and mo2.menu_chosen == []
    r = server.cig_do(APP, bar, {"path": "Tools/Remove orphans"})        # a destructive word in the path: confirm first
    assert not r["ok"] and r["refused"] and r["status"] == "confirm_required" and mo2.menu_chosen == []
    r = server.cig_do(APP, bar, {"path": "Tools/Remove orphans"}, confirm="the owner said: remove them")
    assert r["ok"] and mo2.menu_chosen == ["Tools > Remove orphans"]


def test_an_older_plugin_without_lists_still_works(mo2, idle):
    idle(30)
    mo2.info["reads"] = [x for x in mo2.info["reads"] if x not in ("ui_items", "ui_menus")]
    mo2.info["writes"] = [x for x in mo2.info["writes"] if x not in ("ui_item", "ui_menu")]
    e = Engine([HostMo2Adapter(transport=mo2, instances=lambda: ["X:/MO2"])])
    labels = {a["label"] for a in e.actions(APP)["actions"]}
    assert "invoke Button 'Run'" in labels and not any("TreeItem" in x or "MenuBar" in x for x in labels)
    assert not any(c[0] in ("ui_items", "ui_menus") for c in mo2.calls)
