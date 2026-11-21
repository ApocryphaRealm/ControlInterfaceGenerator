"""The engine: every meta tool goes through here, and every action takes the same path
   resolve app -> fresh snapshot -> re-resolve the element (locator, then fingerprint, else STALE) -> the element must
   still carry the rule -> validate args against the generated schema -> classify -> safety layer -> backup ->
   adapter -> read back -> verify -> log.
Nothing reaches an adapter's execute() without passing policy.decide()."""
from __future__ import annotations

import time
from typing import Optional

import jsonschema

from . import actionlog, appcache, backups, classify, locator, presence, rules
from .adapters.base import Adapter, AdapterError, Target
from .policy import Policy, Request, decide

SNAPSHOT_REUSE_S = 1.5


class Engine:
    def __init__(self, adapters: list[Adapter], policy: Optional[Policy] = None):
        self.adapters = adapters
        self.policy = policy or Policy.load()
        self._snap: dict[str, dict] = {}          # target.key -> {"time", "windows", "elements": {eid: info}}
        # Provenance (Main Agent's order, 2026-11-20, after the Notepad incident): what CIG itself opened and wrote.
        # Kept in memory only: after a server restart nothing counts as CIG's own, so the safe answer is "not ours".
        self.launched: dict[int, dict] = {}       # pid -> {"exe", "time"} for programs started by cig_launch
        self.authored: dict[str, str] = {}        # "<target.key>|<locator>" -> the text CIG last wrote there

    def register_launch(self, pid: int, exe: str) -> None:
        self.launched[int(pid)] = {"exe": exe, "time": time.time()}

    def _provenance_refusal(self, target: Target, node: dict, loc: str, action: str, before: dict) -> Optional[str]:
        """A deny (confirm cannot override): writes go only into windows CIG opened, and a Document is written only
        when it is empty or still holds exactly what CIG wrote there."""
        if not self.policy.write_only_to_launched:
            return None
        if target.adapter == "cli":
            return None                        # a CLI run is a process CIG itself starts, for this one call
        if (target.exe or "").lower() in self.policy.first_party and (target.adapter or "").startswith("host:"):
            # our own host programs (MO2) are driven where the owner runs them - but ONLY through their own channel,
            # whose in-use check and backups apply (Main Agent, 2026-11-20); UIA / CDP writes into an MO2 that CIG
            # did not launch stay refused
            return None
        if target.pid not in self.launched:
            return (f"CIG did not open this window ({target.exe}, pid {target.pid}): writes go only into programs "
                    f"started by cig_launch (confirm cannot override)")
        if action == "set_text" and node.get("control_type") == "Document":
            old = str(before.get("value") or "")
            mine = self.authored.get(f"{target.key}|{loc}")
            if old.strip() and (mine is None or _norm_text(old) != _norm_text(mine)):
                return ("this document holds text CIG did not write (a restored session, an opened file, someone's "
                        "work): CIG writes only into documents it created (confirm cannot override)")
        return None

    # ------------------------------------------------------------------ resolution and snapshots
    def resolve(self, app: str) -> tuple[Adapter, Target]:
        for a in self.adapters:
            t = a.resolve(str(app))
            if t is not None:
                return a, t
        raise AdapterError(f"no adapter can reach '{app}' (call cig_apps for what is running)")

    def _snapshot(self, adapter: Adapter, target: Target, depth: int = 12, fresh: bool = True) -> dict:
        cached = self._snap.get(target.key)
        if cached and not fresh and time.time() - cached["time"] < SNAPSHOT_REUSE_S:
            return cached
        windows = adapter.snapshot(target, depth)
        elements = {}
        for node, loc, parents, win in locator.walk(windows):
            eid = locator.element_id(loc)
            elements[eid] = {"locator": loc, "node": node,
                             "fingerprint": locator.fingerprint(node, parents, win.get("rect"))}
        # keep the previous elements for the fingerprint second chance - from this run, else from the per-app cache
        known = (cached or {}).get("known") or appcache.load_known(target.key)
        menus = set((cached or {}).get("menu_paths") or appcache.load_menu_paths(target.key))
        for node, loc, _p, _w in locator.walk(windows):
            if node.get("control_type") == "MenuBar":
                menus.update(rules.menu_paths(node))
        menus.update(_popup_menu_paths(windows, menus))
        snap = {"time": time.time(), "windows": windows, "elements": elements,
                "known": {**known, **elements}, "menu_paths": sorted(menus)}
        self._snap[target.key] = snap
        appcache.save(target.key, snap)
        return snap

    def _reresolve(self, snap: dict, eid: str) -> tuple[Optional[dict], str]:
        if eid in snap["elements"]:
            return snap["elements"][eid], "exact"
        old = snap["known"].get(eid)
        if not old:
            return None, "unknown element id - call cig_tree or cig_actions first"
        best, best_score = None, 0.0
        for info in snap["elements"].values():
            s = locator.fingerprint_score(old["fingerprint"], info["fingerprint"])
            if s > best_score:
                best, best_score = info, s
        if best is not None and best_score >= locator.MATCH_THRESHOLD:
            return best, f"fingerprint {best_score}"
        return None, "stale: the element is gone or changed - call cig_tree again (never acting on a guess)"

    # ------------------------------------------------------------------ meta tools
    def apps(self) -> list[dict]:
        out = []
        for a in self.adapters:
            lister = getattr(a, "list_apps", None)
            if lister:
                out += lister()
        return out

    def tree(self, app: str, depth: int = 12, max_nodes: int = 400) -> dict:
        adapter, target = self.resolve(app)
        snap = self._snapshot(adapter, target, depth)
        rows = []
        for node, loc, parents, _w in locator.walk(snap["windows"]):
            if len(rows) >= max_nodes:
                break
            row = {"id": locator.element_id(loc), "d": len(parents), "type": node.get("control_type"),
                   "name": (node.get("name") or "")[:80]}
            for k in ("automation_id", "value", "toggle_state", "selected", "expand_state"):
                if node.get(k) not in (None, ""):
                    row[k] = node[k] if k != "value" else str(node[k])[:80]
            if node.get("enabled") is False:
                row["enabled"] = False
            if node.get("patterns"):
                row["patterns"] = node["patterns"]
            rows.append(row)
        return {"ok": True, "target": target.as_dict(), "count": len(snap["elements"]), "shown": len(rows),
                "elements": rows}

    def actions(self, app: str, depth: int = 12) -> dict:
        adapter, target = self.resolve(app)
        snap = self._snapshot(adapter, target, depth)
        acts = rules.actions_for(snap["windows"], getattr(adapter, "rules_name", "uia"))
        for a in acts:
            a.pop("locator", None)
            if a["action"] == "menu" and snap.get("menu_paths"):
                # paths seen so far, this run or an earlier one (a submenu is in the tree only while it is open)
                a["input_schema"]["properties"]["path"]["examples"] = snap["menu_paths"][:80]
        return {"ok": True, "target": target.as_dict(), "actions": acts}

    def read(self, app: str, element_id: str) -> dict:
        adapter, target = self.resolve(app)
        snap = self._snapshot(adapter, target)
        info, how = self._reresolve(snap, element_id)
        if not info:
            return {"ok": False, "error": how}
        st = adapter.read(target, info["locator"], info["node"])
        actionlog.write({"app": target.exe, "action": "read", "kind": "read", "element": info["locator"],
                         "result": "ok"})
        return {"ok": True, "resolved": how, "state": st}

    def do(self, app: str, action_id: str, args: Optional[dict] = None, dry_run: bool = False,
           confirm: Optional[str] = None) -> dict:
        args = dict(args or {})
        entry = {"app": app, "action_id": action_id, "args": args, "dry_run": dry_run, "confirm": confirm}
        result = {"ok": False, "refused": False, "reason": "", "changed": None, "backup": None}

        def finish(**kw):
            result.update(kw)
            entry.update({k: result[k] for k in ("ok", "refused", "reason")})
            entry["changed"] = result.get("changed")
            entry["backup"] = result.get("backup")
            result["log_id"] = actionlog.write(entry)
            return result

        try:
            adapter, target = self.resolve(app)
        except AdapterError as e:
            return finish(reason=str(e))
        entry.update({"app": target.exe, "pid": target.pid, "adapter": adapter.name})
        if "." not in action_id:
            return finish(reason="action_id must be '<element>.<action>' as listed by cig_actions")
        eid, action = action_id.split(".", 1)
        snap = self._snapshot(adapter, target)
        info, how = self._reresolve(snap, eid)
        if not info:
            return finish(refused=True, reason=how)
        node, loc = info["node"], info["locator"]
        if action == "set_secret" or node.get("is_password"):
            entry["args"] = "<redacted>"                 # never log what was meant for a password field
        entry["element"] = loc
        entry["resolved"] = how
        rule = rules.find_rule(action, node, getattr(adapter, "rules_name", "uia"))
        if not rule:
            return finish(refused=True, reason=f"the element no longer offers '{action}' (call cig_actions)")
        schema = rules._schema(rule, node)
        try:
            jsonschema.validate(args, schema)
        except jsonschema.ValidationError as e:
            return finish(reason=f"bad args: {e.message}", schema=schema)

        texts = [node.get("name", "")]
        texts += [str(args[k]) for k in ("button", "path", "option") if k in args]
        if hasattr(adapter, "classify_texts"):
            texts += adapter.classify_texts(node, args)      # e.g. the descriptions of the CLI switches used
        kind, why = classify.classify(action, rule.get("kind"), texts if action != "set_text" else [])
        before = adapter.read(target, loc, node)
        # Replacing text that is already there is an overwrite (plan 2.6: destructive), whatever the element is called:
        # the program may have restored someone's own document into it (Notepad session restore, 2026-11-20).
        if action == "set_text" and kind != "read":
            old = str(before.get("value") or "")
            mine = self.authored.get(f"{target.key}|{loc}")
            ours = mine is not None and _norm_text(old) == _norm_text(mine)
            if old.strip() and not ours and _norm_text(old) != _norm_text(args.get("text", "")):
                kind = "destructive"
                why = why + [f"replaces {len(old)} characters of existing text"]
        entry.update({"kind": kind, "classify": why})
        if kind != "read":
            deny = self._provenance_refusal(target, node, loc, action, before)
            if deny:
                return finish(refused=True, status="refused", reason=deny,
                              preview={"element": loc, "action": action, "kind": kind, "before": before})
        pres = presence.read()
        entry["presence"] = pres.as_dict()
        req = Request(app=target.exe, action=action, kind=kind, pid=target.pid, window_title=target.title,
                      element=loc, confirm=confirm, dry_run=dry_run, elevated_target=target.elevated)
        dec = decide(req, pres, self.policy)
        entry["policy"] = dec.as_dict()
        files = _files_written(adapter, target, action, args, node)
        preview = {"element": loc, "label": node.get("name") or node.get("control_type"), "action": action,
                   "args": args, "kind": kind, "before": before, "will_back_up": files}
        if hasattr(adapter, "describe"):
            preview["would_run"] = adapter.describe(target, node, action, args)
        if not dec.allowed:
            return finish(refused=True, reason=dec.reason, status=dec.status, preview=preview)
        if dec.status == "dry_run":
            if hasattr(adapter, "dry_run_preview"):
                # the program's own dry run where it has one (PowerShell -WhatIf): it changes nothing by contract
                preview["program_dry_run"] = adapter.dry_run_preview(target, node, action, args)
            return finish(ok=True, status="dry_run", reason="dry run - nothing done", preview=preview)

        if files:
            result["backup"] = backups.take(target.exe, action, files)
        if hasattr(adapter, "set_confirm"):
            # a host channel has its own in-use check and logs who approved: it gets the same note (M3)
            adapter.set_confirm(confirm)
        try:
            detail = adapter.execute(target, loc, node, action, args)
        except AdapterError as e:
            if getattr(e, "refused", False):
                # the program itself said no (a host channel's in-use check): a refusal, not a failure
                return finish(refused=True, status="refused", reason=str(e), preview=preview)
            # An action that closes its own element (a dialog button, a window) can raise because the element died
            # during the call (seen: Qt 5 QMessageBox OK, 2026-11-20). The read-back decides, not the exception.
            if rule.get("verify") == "gone":
                try:
                    after = adapter.read(target, loc, node)
                except AdapterError:
                    after = {"exists": False}
                if not after.get("exists", True):
                    entry["adapter_error"] = str(e)
                    return finish(ok=True, status="ok", changed={"before": before, "after": after}, verified=True,
                                  reason="", note="the adapter raised, but the read-back shows the element gone")
            return finish(reason=f"adapter failed: {e}", changed={"before": before})
        after = adapter.read(target, loc, node)
        if not after.get("exists", True) and rule.get("verify") != "gone":
            # the write may have changed the element's own path (a container named after the text just typed):
            # find it again the same way an action would - exact locator, else fingerprint, never a guess
            info2, how2 = self._reresolve(self._snapshot(adapter, target), eid)
            if info2:
                after = adapter.read(target, info2["locator"], info2["node"])
                entry["read_back_resolved"] = how2
                if action == "set_text":
                    loc = info2["locator"]
        verified = verify(rule.get("verify"), action, args, after)
        if action == "set_text" and verified is not False:
            self.authored[f"{target.key}|{loc}"] = str(args["text"])
        return finish(ok=verified is not False, status="ok", detail=detail,
                      changed={"before": before, "after": after}, verified=verified,
                      reason="" if verified is not False else "read-back does not match what was set")

    def wait(self, app: str, element_id: Optional[str] = None, state: str = "exists",
             title_contains: Optional[str] = None, timeout_s: float = 10.0) -> dict:
        t0 = time.time()
        while True:
            try:
                adapter, target = self.resolve(app)
                snap = self._snapshot(adapter, target)
                if element_id:
                    present = element_id in snap["elements"]
                    if present == (state == "exists"):
                        return {"ok": True, "waited_s": round(time.time() - t0, 2)}
                elif title_contains:
                    if any(title_contains.lower() in (w.get("name") or "").lower() for w in snap["windows"]):
                        return {"ok": True, "waited_s": round(time.time() - t0, 2)}
            except AdapterError:
                if state == "gone":
                    return {"ok": True, "waited_s": round(time.time() - t0, 2), "note": "app gone"}
            if time.time() - t0 > timeout_s:
                return {"ok": False, "error": "timeout", "waited_s": round(time.time() - t0, 2)}
            time.sleep(0.25)


def _files_written(adapter, target, action, args, node) -> list:
    """Adapters that need the element to know what a call writes (the CLI: a command's archive argument) take it as
    a keyword; the others keep the plain signature."""
    try:
        return adapter.files_written(target, action, args, node=node)
    except TypeError:
        return adapter.files_written(target, action, args)


def _norm_text(s: str) -> str:
    return str(s).replace("\r\n", "\n").replace("\r", "\n").strip()


def _popup_menu_paths(windows: list[dict], known: set) -> set:
    """An open submenu shows up as a Menu holding MenuItems (often in its own popup window). Its parent's path is the
    known path whose last part names the menu, so 'File' + popup items 'Open...' -> 'File/Open...'."""
    out = set()
    by_last = {p.split("/")[-1].replace("&", "").lower(): p for p in known}
    for node, _loc, _p, _w in locator.walk(windows):
        if node.get("control_type") != "Menu":
            continue
        parent = by_last.get((node.get("name") or "").replace("&", "").lower())
        if not parent:
            continue
        for c in node.get("children") or []:
            if c.get("control_type") == "MenuItem" and c.get("name"):
                out.add(f"{parent}/{c['name']}")
    return out


def verify(how: Optional[str], action: str, args: dict, after: dict) -> Optional[bool]:
    """True / False when the rule names a read-back, None when it does not."""
    if not how:
        return None
    if how == "value":
        want = args.get("text", args.get("option"))
        return str(after.get("value", "")).replace("\r\n", "\n").rstrip("\r\n") == str(want).replace("\r\n", "\n").rstrip("\r\n")
    if how == "toggle_state":
        return after.get("toggle_state") == ("On" if args.get("checked") else "Off")
    if how == "selected":
        return bool(after.get("selected"))
    if how == "expand_state":
        return after.get("expand_state") == ("Expanded" if args.get("expanded", True) else "Collapsed")
    if how == "range":
        return abs(float((after.get("range") or {}).get("value", 1e18)) - float(args["value"])) < 1e-6
    if how == "gone":
        return not after.get("exists", True)
    return None
