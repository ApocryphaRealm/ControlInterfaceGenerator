"""The host adapter for Mod Organizer 2: CIG's first "plugin host" adapter (plan 4.2, milestone M3).

MO2 carries our plugin MO2 Agent Control, which answers one JSON line per connection on 127.0.0.1 (its
docs/PROTOCOL.md, protocol 1). Since 1.1.0 the plugin reads and operates MO2's own widgets from inside the process:
ui_tree, ui_click, ui_answer_modal, ui_set. This adapter turns ui_tree's reply into the same node format the UIA
adapter produces, so the library's rules (library/rules/uia.json) generate the typed actions with no MO2-specific
rule, and it carries each action out with one of the three write commands. No mouse or keyboard input is sent and no
window is raised - which is why the host channel may drive an MO2 that CIG did not launch (engine: provenance).

What the plugin adds on top of CIG's own safety layer, and this adapter passes through untouched:
  - its in-use check (MO2 in front and input in the last minutes): a refused write comes back as a refusal, and the
    confirm note CIG was given is sent on, so the plugin logs who approved;
  - its backup of the profile's list files before a press (the reply's "backup"); CIG's own backup covers the same
    three files (files_written).

MODALS. A press that opens a dialog does not return until the dialog closes; the plugin then answers
"returned": false with the dialog described. That is not a failure: the next snapshot shows the dialog as a modal
Window whose buttons are its answers (action answer_dialog), and its own controls can be acted on. While a dialog is
open, only that dialog's elements are listed - nothing behind it can be acted on, by the plugin's own rule.

LISTS AND MENUS (plugin 1.1.0 with ui_items / ui_item / ui_menus / ui_menu). A list, table or tree becomes a List or
Tree node whose children are ALL its rows, read page by page (VIEW_PAGE a call, the plugin's own maximum, up to
VIEW_ROWS in all): a row with a box takes
set_checked, any other row select, a tree row with rows under it expand. The window's menu bar and tool bar entries
become one MenuBar node, driven by the library's `menu` action with a path ("Tools/Tool Plugins/My Tool").

An app reference this adapter claims: "mo2", "host:mo2", "host:mo2-agent-control" (the one running MO2 with a live
channel; more than one is an error naming them) or "mo2:<instance folder>". It never claims an exe name or a pid, so
"ModOrganizer.exe" still resolves to the UIA adapter for the cross-check of plan 4.2 item 3.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from pathlib import Path
from typing import Callable, Optional

from .base import Adapter, AdapterError, Target

NAME = "host:mo2-agent-control"
CHANNEL = Path("plugins") / "data" / "ApocryphaAgentControl" / "channel.json"
PROFILE_FILES = ("modlist.txt", "plugins.txt", "loadorder.txt")
MIN_VERSION = (1, 1, 0)          # the window commands arrived in 1.1.0
TREE_REUSE_S = 1.0
TREE_LIMIT = 1000

# ui_tree kind -> (UIA control type, patterns) - what library/rules/uia.json keys on
KIND = {
    "button": ("Button", ["Invoke"]),
    "checkbox": ("CheckBox", ["Toggle"]),
    "radio": ("RadioButton", ["SelectionItem"]),
    "edit": ("Edit", ["Value"]),
    "text": ("Document", ["Value"]),
    "combo": ("ComboBox", ["Selection"]),
    "spin": ("Spinner", ["RangeValue"]),
    "tabs": ("Tab", []),
    "label": ("Text", ["Text"]),
}


class HostRefused(AdapterError):
    """The program itself said no (its in-use check, a wrong token). The engine reports it as a refusal."""
    refused = True


# ---------------------------------------------------------------------------------------------------------------- transport
def read_channel(instance: str) -> dict:
    path = Path(instance) / CHANNEL
    try:
        ch = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AdapterError(f"no channel file {path} - is MO2 running with the MO2 Agent Control plugin installed?")
    if ch.get("host") != "127.0.0.1":
        raise AdapterError(f"the channel file names host {ch.get('host')!r} - only 127.0.0.1 is ever contacted")
    return ch


def _pid_alive(pid) -> bool:
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        return True


def send(instance: str, cmd: str, args: Optional[dict] = None, confirm: Optional[str] = None,
         timeout: float = 120.0) -> dict:
    """One request to the plugin; its reply as a dict. The token is read fresh each time and never logged."""
    ch = read_channel(instance)
    if not _pid_alive(ch.get("pid")):
        raise AdapterError(f"the MO2 that wrote the channel file (pid {ch.get('pid')}) is not running")
    req = {"token": ch["token"], "cmd": cmd, "args": args or {}}
    if confirm and confirm.strip():
        req["confirm"] = confirm.strip()
    try:
        with socket.create_connection(("127.0.0.1", int(ch["port"])), timeout=timeout) as s:
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                part = s.recv(65536)
                if not part:
                    break
                buf += part
    except OSError as e:
        raise AdapterError(f"MO2 did not answer on 127.0.0.1:{ch.get('port')} ({e})")
    try:
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except ValueError:
        raise AdapterError("MO2 sent an unreadable reply")


def running_instances() -> list[str]:
    """The folders of running ModOrganizer.exe processes that hold a live channel file."""
    out = []
    try:
        import psutil
    except ImportError:
        return out
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info["name"] or "").lower() != "modorganizer.exe" or not p.info["exe"]:
                continue
            folder = str(Path(p.info["exe"]).parent)
            ch = json.loads((Path(folder) / CHANNEL).read_text(encoding="utf-8"))
            if int(ch.get("pid", -1)) == p.pid and folder not in out:
                out.append(folder)
        except (OSError, ValueError, TypeError, psutil.Error):
            continue
    return out


# ------------------------------------------------------------------------------------------------- ui_tree -> fixture nodes
def _matches(c: dict, kind: str, name: str, text: str) -> bool:
    """The plugin's own locate() test (ui.py), so an index counted here is the index it counts."""
    if c.get("kind") != kind:
        return False
    if name and c.get("name") != name:
        return False
    if text and c.get("text", c.get("tooltip", "")) != text and c.get("tooltip", "") != text:
        return False
    return True


def host_locator(c: dict, controls: list[dict], window: Optional[str]) -> Optional[dict]:
    """What to send the plugin to name exactly this control: kind + objectName, else its text (a button without text:
    its tooltip), + its index among the controls that same locator matches. None when it has neither."""
    kind = c.get("kind")
    name = c.get("name") or ""
    text = "" if name else (c.get("text") or c.get("tooltip") or "")
    if not name and not text:
        return None
    hits = [x for x in controls if x.get("kind") != "label" and _matches(x, kind, name, text)]
    loc: dict = {"kind": kind}
    if name:
        loc["name"] = name
    if text:
        loc["text"] = text
    if window:
        loc["window"] = window
    if len(hits) > 1:
        loc["index"] = next(i for i, x in enumerate(hits) if x is c)
    return loc


def control_node(c: dict, controls: list[dict], window: Optional[str], unique_names: set) -> list[dict]:
    kind = c.get("kind")
    ct, patterns = KIND.get(kind, ("Custom", []))
    loc = host_locator(c, controls, window) if kind != "label" else None
    label = c.get("text") or c.get("tooltip") or c.get("placeholder") or ""
    node: dict = {"control_type": ct, "name": label, "enabled": bool(c.get("enabled", True)),
                  "patterns": list(patterns) if (loc or kind == "label") else []}
    oname = c.get("name") or ""
    if oname and oname in unique_names:
        node["automation_id"] = oname
    if loc:
        node["host"] = loc
    if c.get("where"):
        node["where"] = c["where"]
    if kind in ("button", "checkbox", "radio"):
        if "checked" in c:
            if kind == "radio":
                node["selected"] = bool(c["checked"])
            else:
                node["toggle_state"] = "On" if c["checked"] else "Off"
                if kind == "button" and loc:
                    node["patterns"] = ["Toggle"]          # a checkable tool button is set, not pressed
    elif kind in ("edit", "text"):
        node["value"] = c.get("value", "")
        node["is_read_only"] = bool(c.get("read_only"))
    elif kind == "combo":
        node["value"] = c.get("value", "")
        node["children"] = [{"control_type": "ListItem", "name": str(it), "patterns": []} for it in c.get("items") or []]
    elif kind == "spin":
        node["range"] = {"min": c.get("min"), "max": c.get("max"), "value": c.get("value")}
        node["value"] = c.get("value")
    elif kind == "tabs":
        kids = []
        for i, it in enumerate(c.get("items") or []):
            kid: dict = {"control_type": "TabItem", "name": str(it), "selected": i == c.get("index"),
                         "patterns": ["SelectionItem"] if loc else []}
            if loc:
                kid["host"] = dict(loc, tab=str(it))
            kids.append(kid)
        node["children"] = kids
    elif kind == "label":
        node["value"] = c.get("text", "")
    return [node]


def window_node(w: dict, controls: Optional[list[dict]], modal: Optional[dict], window_arg: Optional[str],
                rows: Optional[dict] = None, menus: Optional[dict] = None) -> dict:
    """One window as a fixture node. controls None: listed but not readable now (it is behind a modal dialog)."""
    node: dict = {"control_type": "Window", "name": w.get("title") or "", "is_modal": bool(w.get("modal")),
                  "patterns": [], "children": [], "window_class": w.get("class") or ""}
    if w.get("name"):
        node["automation_id"] = w["name"]
    if controls is None:
        node["is_modal"] = False                 # nothing to answer on a window that cannot be reached right now
        node["blocked_by_modal"] = True
        return node
    if modal:
        node["host"] = {"modal": True, "title": modal.get("title") or "", "text": modal.get("text") or ""}
        for key in ("text", "informative"):
            if modal.get(key):
                node["children"].append({"control_type": "Text", "name": key, "value": modal[key], "patterns": ["Text"]})
    counts: dict = {}
    for c in controls:
        n = c.get("name") or ""
        if n and not n.startswith("qt_"):
            counts[n] = counts.get(n, 0) + 1
    unique = {n for n, k in counts.items() if k == 1}
    for c in controls:
        if c.get("kind") == "view":
            node["children"].append(view_node(c, controls, window_arg, unique, (rows or {}).get(id(c))))
        else:
            node["children"] += control_node(c, controls, window_arg, unique)
    if menus:
        node["children"].append(menus)
    return node


def window_ident(w: dict, all_windows: list[dict]) -> Optional[str]:
    """What names this window to the plugin (`window` takes a title or an objectName): its objectName when no other
    visible window shares it, else its title when that is unique, else nothing."""
    def uniq(v):
        return bool(v) and sum(1 for x in all_windows if v in (x.get("title"), x.get("name"))) == 1
    if uniq(w.get("name")):
        return w["name"]
    if uniq(w.get("title")):
        return w["title"]
    return None


# -------------------------------------------------------------------------------------------------------------------- adapter
class HostMo2Adapter(Adapter):
    name = NAME

    def __init__(self, transport: Optional[Callable] = None, instances: Optional[Callable] = None):
        # seams for the tests: transport(instance, cmd, args, confirm) -> reply, instances() -> [folders]
        self._send = transport or send
        self._instances = instances or running_instances
        self._confirm: Optional[str] = None
        self._instance: dict[str, str] = {}       # target.key -> instance folder
        self._tree: dict[str, dict] = {}          # target.key -> {"time", "windows"}
        self._info: dict[str, dict] = {}
        self.last_reply: Optional[dict] = None

    # the engine hands over the caller's confirm note before execute (the plugin logs it beside the change)
    def set_confirm(self, confirm: Optional[str]) -> None:
        self._confirm = confirm

    # ---------------------------------------------------------------- resolve
    def _pick_instance(self, app: str) -> Optional[str]:
        a = app.strip()
        low = a.lower()
        if low.startswith("mo2:") and len(a) > 4:
            return a[4:].strip().strip('"')
        if low not in ("mo2", "host:mo2", NAME):
            return None
        env = os.environ.get("CIG_MO2_INSTANCE", "").strip()
        if env:
            return env
        found = self._instances()
        if not found:
            raise AdapterError("no running Mod Organizer 2 with a live MO2 Agent Control channel was found "
                               "(start MO2 with the plugin installed, or name the instance: 'mo2:<folder>')")
        if len(found) > 1:
            raise AdapterError("more than one MO2 is running with the plugin - name one: "
                               + "; ".join(f"'mo2:{f}'" for f in found))
        return found[0]

    def resolve(self, app: str) -> Optional[Target]:
        instance = self._pick_instance(str(app))
        if instance is None:
            return None
        info = self._call(instance, "info")
        ver = str(info.get("version") or "")
        try:
            too_old = tuple(int(x) for x in ver.split(".")[:3]) < MIN_VERSION
        except ValueError:
            too_old = True
        if too_old or "ui_tree" not in (info.get("reads") or []):
            raise AdapterError(f"MO2 Agent Control {ver or '?'} in this MO2 has no window commands - 1.1.0 or newer is needed")
        # the instance is part of the identity, as a short hash: the key names cache files, and a folder path is nobody's business
        tag = hashlib.sha1(os.path.normcase(os.path.normpath(instance)).encode("utf-8")).hexdigest()[:8]
        key = f"ModOrganizer.exe|agent-control-{ver}|{NAME}|{tag}"
        self._instance[key] = instance
        self._info[key] = info
        return Target(key=key, exe="ModOrganizer.exe", pid=info.get("pid"), title=f"Mod Organizer 2 - {info.get('profile', '')}",
                      adapter=self.name)

    def list_apps(self) -> list[dict]:
        out = []
        for folder in self._instances():
            out.append({"app": f"mo2:{folder}", "exe": "ModOrganizer.exe", "adapter": self.name,
                        "note": "Mod Organizer 2 through its own plugin channel (MO2 Agent Control)"})
        return out

    # ---------------------------------------------------------------- the channel
    def _call(self, instance: str, cmd: str, args: Optional[dict] = None, confirm: Optional[str] = None) -> dict:
        reply = self._send(instance, cmd, args or {}, confirm)
        if not isinstance(reply, dict):
            raise AdapterError("MO2 sent an unreadable reply")
        if reply.get("ok"):
            return reply
        if reply.get("refused"):
            raise HostRefused(f"MO2 Agent Control refused: {reply.get('error')}")
        raise AdapterError(f"MO2 Agent Control: {reply.get('error')}")

    def _inst(self, target: Target) -> str:
        try:
            return self._instance[target.key]
        except KeyError:
            raise AdapterError("this MO2 was not resolved in this run - call cig_tree first")

    # ---------------------------------------------------------------- snapshot
    def _windows(self, target: Target, fresh: bool) -> list[dict]:
        cached = self._tree.get(target.key)
        if cached and not fresh and time.time() - cached["time"] < TREE_REUSE_S:
            return cached["windows"]
        inst = self._inst(target)
        top = self._call(inst, "ui_tree", {"labels": True, "limit": TREE_LIMIT})
        wins = top.get("windows") or []
        modal = top.get("modal")
        out = []
        if modal:
            # only the dialog can be read into and acted on; the windows behind it are listed, empty
            shown = top.get("window") or {}
            placed = False
            for w in wins:
                is_it = (not placed and w.get("modal") and w.get("title") == shown.get("title")
                         and w.get("class") == shown.get("class") and w.get("name") == shown.get("name"))
                if is_it:
                    cs = top.get("controls") or []
                    out.append(window_node(w, cs, modal, None, self._rows(inst, cs, None)))
                    placed = True
                else:
                    out.append(window_node(w, None, None, None))
            if not placed:
                out.append(window_node(dict(shown, modal=True), top.get("controls") or [], modal, None))
        else:
            for w in wins:
                ident = window_ident(w, wins)
                if ident is None:
                    out.append(window_node(w, [], None, None))       # cannot be named: listed, nothing actionable
                    continue
                one = self._call(inst, "ui_tree", {"window": ident, "labels": True, "limit": TREE_LIMIT})
                cs = one.get("controls") or []
                out.append(window_node(w, cs, None, ident, self._rows(inst, cs, ident), self._menus(inst, ident)))
        self._tree[target.key] = {"time": time.time(), "windows": out}
        return out

    def _rows(self, inst: str, controls: list[dict], window: Optional[str]) -> dict:
        """{id(control): the plugin's ui_items reply} for every list, table and tree among the controls."""
        out = {}
        if not self._has(inst, "ui_items"):
            return out
        unique: set = set()
        for c in controls:
            if c.get("kind") != "view" or not c.get("rows"):
                continue
            loc = view_node(c, controls, window, unique, None)["host"]
            try:
                out[id(c)] = self._all_rows(inst, _view_loc(loc))
            except AdapterError:
                continue                    # a list that cannot be read stays a list with no rows
        return out

    def _all_rows(self, inst: str, view_loc: dict) -> dict:
        """Every row of one list, page by page through the plugin's own paging (its 'next'), up to VIEW_ROWS. A snapshot
        holding only the first page left every row past it out of reach (request ad4d, 2026-11-21: the scratch mod
        list's only rows with a box were 78-85 and the snapshot held rows 0-59)."""
        first = self._call(inst, "ui_items", dict(view_loc, limit=VIEW_PAGE))
        rows, nxt = list(first.get("rows") or []), first.get("next")
        while nxt is not None and len(rows) < VIEW_ROWS:
            if not isinstance(nxt, int) or isinstance(nxt, bool) or (rows and nxt <= rows[-1].get("row", -1)):
                break                       # a cursor that does not move on is never followed round in a loop
            page = self._call(inst, "ui_items", dict(view_loc, start=nxt, limit=min(VIEW_PAGE, VIEW_ROWS - len(rows))))
            got = page.get("rows") or []
            if not got:
                break
            rows.extend(got)
            nxt = page.get("next")
        return dict(first, rows=rows, next=nxt)

    def _menus(self, inst: str, window: Optional[str]) -> Optional[dict]:
        if not window or not self._has(inst, "ui_menus"):
            return None
        try:
            return menu_node(self._call(inst, "ui_menus", {"window": window}).get("entries") or [], window)
        except AdapterError:
            return None

    def _has(self, inst: str, cmd: str) -> bool:
        """Does this MO2's plugin know the command? (lists and menus arrived after the first window commands)"""
        info = next((i for k, i in self._info.items() if self._instance.get(k) == inst), None) or {}
        return cmd in (info.get("reads") or []) + (info.get("writes") or [])

    def snapshot(self, target: Target, depth: int = 12) -> list[dict]:
        return json.loads(json.dumps(self._windows(target, fresh=True)))

    def _find(self, target: Target, locator: str, fresh: bool) -> Optional[dict]:
        from .. import locator as loc_mod
        for node, loc, _p, _w in loc_mod.walk(self._windows(target, fresh)):
            if loc == locator:
                return node
        return None

    # ---------------------------------------------------------------- read
    def read(self, target: Target, locator: str, node: dict) -> dict:
        live = self._find(target, locator, fresh=False)
        if live is None:
            return {"exists": False}
        keys = ("name", "value", "toggle_state", "selected", "expand_state", "range", "enabled")
        return {"exists": True, **{k: live[k] for k in keys if k in live}}

    # ---------------------------------------------------------------- execute
    def execute(self, target: Target, locator: str, node: dict, action: str, args: dict) -> dict:
        inst = self._inst(target)
        live = self._find(target, locator, fresh=False)
        if live is None:
            raise AdapterError(f"element gone: {locator}")
        host = live.get("host")
        if action == "list_items" and host and host.get("view"):
            r = self._call(inst, "ui_items", dict(_view_loc(host), limit=int(args.get("limit", 200)) if args else 200))
            return {"detail": f"{r.get('total')} rows", "columns": [c.get("title") for c in r.get("columns") or []],
                    "rows": r.get("rows"), "next": r.get("next")}
        if action in ("get_text", "list_items"):
            return {"detail": live.get("value", ""), "items": [c.get("name") for c in live.get("children") or []]}
        if not host:
            raise AdapterError("this element cannot be named to MO2 Agent Control (no objectName and no text)")
        confirm, self._confirm = self._confirm, None
        if action == "answer_dialog":
            if not host.get("modal"):
                raise AdapterError("this window is not the open modal dialog")
            a = {"text": str(args["button"])}
            expect = host.get("title") or (host.get("text") or "")[:60]
            if expect:
                a["expect"] = expect
            cmd = "ui_answer_modal"
        elif host.get("menu"):
            if action != "menu":
                raise AdapterError(f"the menus take the 'menu' action, not '{action}'")
            want = str(args["path"]).strip().strip("/")
            real = host["paths"].get(want) or next((v for k, v in host["paths"].items() if k.lower() == want.lower()), None)
            if not real:
                raise AdapterError(f"no menu entry '{want}' - entries: " + "; ".join(sorted(host["paths"])[:25]))
            cmd, a = "ui_menu", {"path": real}
            if host.get("window"):
                a["window"] = host["window"]
        elif host.get("item"):
            verb = {"set_checked": lambda: "check" if args["checked"] else "uncheck", "select": lambda: "select",
                    "expand": lambda: "expand" if args.get("expanded", True) else "collapse"}.get(action)
            if verb is None:
                raise AdapterError(f"a row cannot '{action}'")
            cmd, a = "ui_item", dict(_view_loc(host), action=verb())
            a.update({"match": host["match"]} if "match" in host else {"row": host["row"]})
        elif action == "invoke":
            cmd, a = "ui_click", _loc(host)
        elif action == "set_checked":
            cmd, a = "ui_set", dict(_loc(host), value=bool(args["checked"]))
        elif action == "select":
            if "tab" in host:
                cmd, a = "ui_set", dict(_loc(host), value=host["tab"])
            else:
                cmd, a = "ui_set", dict(_loc(host), value=True)
        elif action == "choose":
            cmd, a = "ui_set", dict(_loc(host), value=str(args["option"]))
        elif action == "set_text":
            cmd, a = "ui_set", dict(_loc(host), value=str(args["text"]))
        elif action == "set_number":
            v = args["value"]
            cmd, a = "ui_set", dict(_loc(host), value=int(v) if float(v).is_integer() else float(v))
        else:
            raise AdapterError(f"the MO2 host channel cannot '{action}' (no keys or mouse are ever sent)")
        self._tree.pop(target.key, None)             # whatever happens next, the tree is stale
        reply = self._call(inst, cmd, a, confirm)
        self.last_reply = reply
        out = {"detail": f"{cmd} through MO2 Agent Control", "returned": reply.get("returned"),
               "host_backup": reply.get("backup")}
        if reply.get("modal"):
            m = reply["modal"]
            out["modal_open"] = {"title": m.get("title"), "text": m.get("text"),
                                 "buttons": [b.get("text") for b in m.get("buttons") or []]}
            if reply.get("returned") is False:
                out["note"] = ("the press opened a dialog and is waiting in it: cig_actions now lists the dialog "
                               "(answer_dialog, or act on its controls)")
        if cmd in ("ui_set", "ui_item") and reply.get("applied") is False:
            raise AdapterError(f"MO2 holds {reply.get('value')!r} after the set, not {reply.get('asked')!r}")
        return out

    # ---------------------------------------------------------------- backups
    def files_written(self, target: Target, action: str, args: dict) -> list[str]:
        """A press in MO2 can rewrite the profile's lists (Apply, Restore): CIG backs the three files up first, beside
        the plugin's own copy. Value sets (a filter box, a tab) write nothing."""
        if action not in ("invoke", "answer_dialog", "set_checked", "menu"):
            return []
        info = self._info.get(target.key) or {}
        inst, prof = info.get("instance") or self._instance.get(target.key), info.get("profile")
        if not inst or not prof:
            return []
        folder = Path(inst) / "profiles" / prof
        return [str(folder / f) for f in PROFILE_FILES if (folder / f).is_file()]


def _loc(host: dict) -> dict:
    return {k: host[k] for k in ("kind", "name", "text", "window", "index") if k in host}


def _view_loc(host: dict) -> dict:
    """The plugin's locator of a list: its objectName, or kind=view with the window and its index."""
    out = {k: host[k] for k in ("name", "window", "index") if k in host}
    if "name" not in out:
        out["kind"] = "view"
    return out


# ------------------------------------------------------------------------------- lists, trees and menus (plugin 1.1.0+)
VIEW_PAGE = 1000        # rows a ui_items call returns at most (the plugin's MAX_ROWS)
VIEW_ROWS = 20000       # every row of a list is read into a snapshot, page by page, up to this many


def view_node(c: dict, controls: list[dict], window: Optional[str], unique_names: set, rows_reply: Optional[dict]) -> dict:
    """A list, table or tree as a node whose children are its rows (all of them, VIEW_ROWS at most). A row with a box is settable (set_checked),
    any other row selectable; a tree row with rows under it can be opened."""
    loc = host_locator(c, controls, window)
    if loc is None:                                   # no objectName: kind + its place among the window's views
        views = [x for x in controls if x.get("kind") == "view" and not x.get("name")]
        loc = {"kind": "view"}
        if window:
            loc["window"] = window
        if len(views) > 1:
            loc["index"] = next(i for i, x in enumerate(views) if x is c)
    is_tree = bool(c.get("tree"))
    node: dict = {"control_type": "Tree" if is_tree else "List", "name": c.get("name") or "", "patterns": [],
                  "enabled": bool(c.get("enabled", True)), "children": [], "host": dict(loc, view=True),
                  "rows_total": c.get("rows")}
    oname = c.get("name") or ""
    if oname and oname in unique_names:
        node["automation_id"] = oname
    rows = (rows_reply or {}).get("rows") or []
    firsts = [(r.get("cells") or [""])[0] for r in rows]
    complete = (rows_reply or {}).get("next") is None
    for r in rows:
        cells = r.get("cells") or [""]
        kid: dict = {"control_type": "TreeItem" if is_tree else "ListItem", "name": cells[0], "value": " | ".join(cells),
                     "patterns": [], "enabled": r.get("enabled", True) is not False}
        how = {"match": cells[0]} if complete and cells[0] and firsts.count(cells[0]) == 1 else {"row": r["row"]}
        kid["host"] = dict(loc, item=True, expect=cells[0], **how)
        if "checked" in r:
            kid["toggle_state"] = "On" if r["checked"] is True else "Off" if r["checked"] is False else "Indeterminate"
        if "checked" in r and r.get("checkable", True) and r.get("enabled", True) is not False:
            kid["patterns"].append("Toggle")
        else:
            # no box, or a box that is shown but not the person's to tick (a game's own master): the row can be
            # selected and its state read, never set
            kid["patterns"].append("SelectionItem")
        kid["selected"] = bool(r.get("selected"))
        if r.get("children") and is_tree:
            kid["patterns"].append("ExpandCollapse")
            kid["expand_state"] = "Expanded" if r.get("expanded") else "Collapsed"
        node["children"].append(kid)
    if not complete:
        node["rows_shown"] = len(rows)
    return node


def menu_node(entries: list[dict], window: Optional[str]) -> Optional[dict]:
    """The window's menu bar and tool bar entries as one MenuBar node (the library's 'menu' action takes a path)."""
    if not entries:
        return None
    root: dict = {"control_type": "MenuBar", "name": "Menus", "patterns": [], "children": [],
                  "host": {"menu": True, "window": window, "paths": {}}}
    by_path = {(): root}
    for e in entries:
        parts = [p.strip() for p in str(e.get("path", "")).split(" > ")]
        parent = by_path.get(tuple(parts[:-1]))
        if parent is None or not parts[-1]:
            continue
        item: dict = {"control_type": "MenuItem", "name": parts[-1], "patterns": [], "enabled": bool(e.get("enabled", True)),
                      "children": []}
        if "checked" in e:
            item["toggle_state"] = "On" if e["checked"] else "Off"
        parent["children"].append(item)
        by_path[tuple(parts)] = item
        if not e.get("menu") and e.get("enabled", True):
            root["host"]["paths"]["/".join(parts)] = e["path"]
    return root
